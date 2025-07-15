import asyncio
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

import sys
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

# rich 콘솔
console = Console()

class Category(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class CrawlerConfig:
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10
    max_more_clicks: int = 20

class ChosunCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://www.chosun.com/economy/"
    }

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.article_service = ArticleService()
        self.media_id = None
        self.bias = None

    async def _get_media_info(self):
        # media_outlets 테이블에서 자동 조회, 없으면 기본값
        info = await self.article_service.get_or_create_media("조선일보")
        if info:
            self.media_id = info.get("id", "ef740f3f-c9d1-4316-a679-3ab4e87971ce")
            self.bias = info.get("bias", "right")
        else:
            self.media_id = "ef740f3f-c9d1-4316-a679-3ab4e87971ce"
            self.bias = "right"

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict]:
        url = self.CATEGORY_URLS[category]
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
        articles: List[Dict] = []
        seen_urls: Set[str] = set()
        more_clicks = 0
        # rich 진행률
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console) as progress:
            task = progress.add_task(f"[bold blue]{category.value} 기사 수집", total=self.config.articles_per_category)
            while len(articles) < self.config.articles_per_category and more_clicks < self.config.max_more_clicks:
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                story_cards = soup.select(".story-card__headline")
                for a in story_cards:
                    href = a.get("href")
                    if not href or not isinstance(href, str) or not href.startswith("/"):
                        continue
                    article_url = "https://www.chosun.com" + href
                    if article_url in seen_urls:
                        continue
                    # 상세 정보 추출
                    detail = await self._extract_article_detail(browser, article_url)
                    if detail and detail.get("content_full") and isinstance(detail["content_full"], str) and len(detail["content_full"]) >= self.config.min_content_length:
                        detail["url"] = article_url
                        detail["category"] = category.value
                        articles.append(detail)
                        seen_urls.add(article_url)
                        progress.update(task, advance=1)
                        if len(articles) >= self.config.articles_per_category:
                            break
                if len(articles) < self.config.articles_per_category:
                    # 더보기 버튼 클릭
                    try:
                        more_btn = await page.query_selector("#load-more-stories")
                        if more_btn:
                            await more_btn.click()
                            await page.wait_for_timeout(1200)
                            more_clicks += 1
                        else:
                            break
                    except Exception:
                        break
        await page.close()
        return articles

    async def _extract_article_detail(self, browser: Browser, url: str) -> Optional[Dict]:
        import re
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            # 제목
            title_tag = soup.select_one("h1")
            title = title_tag.get_text(strip=True) if title_tag else None
            # 본문 (section.article-body > p)
            body_section = soup.select_one("section.article-body[itemprop='articleBody']")
            content = ""
            if body_section:
                paragraphs = body_section.select("p.article-body__content-text")
                content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            # 기자명
            author_tag = soup.select_one("span.article-byline__author")
            author = author_tag.get_text(strip=True) if author_tag else None
            # 발행일 (inputDate, upDate 우선순위, 접두어 robust)
            published_at = None
            date_tag = soup.select_one("span.inputDate")
            if date_tag:
                import re
                m = re.search(r"(입력|업데이트)\s*(\d{4}\.\d{2}\.\d{2}\. \d{2}:\d{2})", date_tag.get_text())
                if m:
                    date_str = m.group(2)
                    published_at = date_str.replace('.', '-').replace(' ', 'T').replace('-T', 'T') + ':00'
                    console.print(f"[green]published_at 파싱 성공: {published_at}[/green]")
                else:
                    console.print(f"[yellow]published_at 파싱 실패(inputDate): {date_tag.get_text()}[/yellow]")
            else:
                date_tag = soup.select_one("span.upDate")
                if date_tag:
                    m = re.search(r"(입력|업데이트)\s*(\d{4}\.\d{2}\.\d{2}\. \d{2}:\d{2})", date_tag.get_text())
                    if m:
                        date_str = m.group(2)
                        published_at = date_str.replace('.', '-').replace(' ', 'T').replace('-T', 'T') + ':00'
                        console.print(f"[green]published_at 파싱 성공: {published_at}[/green]")
                    else:
                        console.print(f"[yellow]published_at 파싱 실패(upDate): {date_tag.get_text()}[/yellow]")
                else:
                    console.print(f"[yellow]published_at 태그 자체 없음: {url}[/yellow]")
            # 대표 이미지
            image_tag = soup.select_one("meta[property='og:image']")
            image_url = image_tag["content"] if image_tag and image_tag.has_attr("content") else None
            return {
                "title": title,
                "content_full": content,
                "published_at": published_at,
                "author": author,
                "image_url": image_url
            }
        except Exception:
            return None
        finally:
            await page.close()

    def _parse_datetime(self, dt: Optional[str]) -> Optional[datetime]:
        if not dt or isinstance(dt, list):
            return None
        try:
            # 2024-07-15T09:00:00+09:00 형식
            return datetime.fromisoformat(dt)
        except Exception:
            return None

    async def crawl_all_categories(self):
        await self._get_media_info()
        all_articles = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for category in self.CATEGORY_URLS.keys():
                articles = await self.crawl_category(browser, category)
                for art in articles:
                    article = Article(
                        title=art.get("title") or "",
                        url=art.get("url") or "",
                        category=art.get("category") or "",
                        content_full=art.get("content_full"),
                        published_at=parse_datetime_str(art.get("published_at")),
                        author=art.get("author"),
                        image_url=art.get("image_url"),
                        bias=self.bias or "center",
                        media_id=self.media_id
                    )
                    all_articles.append(article)
            await browser.close()
        return all_articles

    async def save_articles(self, articles):
        return await self.article_service.save_articles(articles)

def parse_datetime_str(dt_str):
    if not dt_str or not isinstance(dt_str, str):
        return None
    try:
        dt_str = dt_str.replace('-T', 'T')
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

async def main():
    config = CrawlerConfig()
    crawler = ChosunCrawler(config)
    console.print("[bold green]조선일보 크롤러 시작!")
    articles = await crawler.crawl_all_categories()
    if articles is None:
        articles = []
    saved = await crawler.save_articles(articles)
    if saved is None:
        saved = 0
    console.print(f"[bold cyan]총 {len(articles)}개 기사 크롤링, DB 저장 {saved}건 완료!")

if __name__ == "__main__":
    asyncio.run(main())
