import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass
from enum import Enum

import aiofiles
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
from bs4 import Tag, NavigableString

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.theme import Theme
from rich.live import Live
from rich.spinner import Spinner

# Supabase 연동 import
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler
from apps.backend.crawler.utils import dict_to_article

console = Console(theme=Theme({
    "success": "bold green",
    "fail": "bold red",
    "info": "bold cyan"
}))

def print_status(msg, status="info"):
    console.print(msg, style=status)

# 로깅 설정
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
file_handler = logging.FileHandler(log_dir / "crawler_mbc.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
file_handler.setFormatter(file_formatter)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(message)s")
console_handler.setFormatter(console_formatter)
logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)

class Category(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class CrawlerConfig:
    max_pages: int = 10
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 30
    min_title_length: int = 10

class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 MBC 뉴스 크롤러 시작")
    @staticmethod
    def print_category_start(category: str):
        console.print(f"[bold cyan]\n📰 {category} 카테고리 크롤링 중...[/bold cyan]")
    @staticmethod
    def print_category_complete(category: str, count: int):
        console.print(f"[bold green]✅ {category}: {count}개 기사 수집 완료[/bold green]")
    @staticmethod
    def print_summary(total_articles: int, filepath: str):
        console.rule("[bold magenta]🎉 크롤링 완료!")
        console.print(f"[bold yellow]📊 총 {total_articles}개 기사 수집")
        console.print(f"[bold yellow]💾 저장 위치: {filepath}")
        console.rule()
    @staticmethod
    def print_progress(category: str, current: int, target: int, total_articles: int):
        progress = min(100, int(current / target * 100))
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        console.print(f"   {bar} {current}/{target} ({progress}%) - 총 {total_articles}개 기사", end="\r")

class MbcCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://imnews.imbc.com/news/2025/econo/"
    }
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.ui = ConsoleUI()
        self.article_service = ArticleService()
        self.media_name = "MBC 뉴스"
        self.media_id = None
        self.bias = None

    async def _get_media_info(self):
        info = await self.article_service.get_or_create_media(self.media_name)
        self.media_id = info["id"] if info else "f28f48c4-ee6b-4e11-a8d5-a4673a9ba9d6"
        self.bias = info["bias"] if info else "center"

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        self.ui.print_category_start(category.value)
        url = self.CATEGORY_URLS[category]
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
        article_candidates: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()
        current_page = 1
        # 1. 페이지네이션을 따라가며 중복 없는 기사 30개 모으기
        while len(article_candidates) < self.config.articles_per_category and current_page <= self.config.max_pages:
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            # 기사 리스트 파싱
            for li in soup.select(".list_area .thumb_type.list_thumb_c > li.item"):
                a = li.find("a", href=True)
                if not a or not isinstance(a, Tag):
                    continue
                url_ = a.get("href")
                if isinstance(url_, list):
                    url_ = url_[0] if url_ else None
                if not url_:
                    continue
                if not isinstance(url_, str):
                    continue
                if not url_.startswith("http"):
                    url_ = "https://imnews.imbc.com" + url_
                if url_ in seen_urls:
                    continue
                title_tag = li.select_one(".tit")
                title = title_tag.get_text(strip=True) if title_tag else None
                summary_tag = li.select_one(".sub")
                summary = summary_tag.get_text(strip=True) if summary_tag else None
                reporter_tag = li.select_one(".sub2 span")
                reporter = reporter_tag.get_text(strip=True) if reporter_tag else None
                img_tag = li.select_one(".img img")
                image_url = None
                if img_tag:
                    src = img_tag.get("src")
                    if isinstance(src, list):
                        src = src[0] if src else None
                    if src and isinstance(src, str) and src.startswith("//"):
                        image_url = "https:" + src
                    elif src and isinstance(src, str):
                        image_url = src
                article_candidates.append({
                    "url": url_,
                    "title": title,
                    "summary": summary,
                    "author": reporter,
                    "image_url": image_url
                })
                seen_urls.add(url_)
                if len(article_candidates) >= self.config.articles_per_category:
                    break
            # 다음 페이지 이동
            next_btn = soup.select_one(".btn_view.btn_more")
            next_btn_style = str(next_btn.get("style")) if next_btn and hasattr(next_btn, 'get') else ""
            if next_btn and next_btn_style.find("display: none") == -1:
                current_page += 1
                next_url = url + f"#page={current_page}"
                await page.goto(next_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await page.wait_for_timeout(self.config.wait_timeout)
            else:
                break
        await page.close()
        # 2. 상세 기사 추출(진행률 표시)
        detailed_articles = []
        detail_page = await browser.new_page()
        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), "[progress.percentage]{task.percentage:>3.0f}%", TimeElapsedColumn(), console=console) as progress:
                task = progress.add_task(f"[cyan]{category.value} 기사 상세 추출", total=len(article_candidates))
                for idx, art in enumerate(article_candidates):
                    detail = await self._extract_article_detail_from_page(detail_page, art["url"])
                    if detail and detail.get("content_full"):
                        art.update(detail)
                        art["category"] = category.value
                        art["media_id"] = self.media_id
                        art["bias"] = self.bias
                        detailed_articles.append(art)
                    progress.update(task, advance=1)
                    if len(detailed_articles) >= self.config.articles_per_category:
                        break
        finally:
            await detail_page.close()
        self.ui.print_category_complete(category.value, len(detailed_articles))
        return detailed_articles

    async def _extract_article_detail_from_page(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            # 제목
            title = soup.select_one("h2.art_title")
            title = title.get_text(strip=True) if title else None
            # 본문
            content_tag = soup.select_one("div.news_txt[itemprop='articleBody']")
            content = content_tag.get_text("\n", strip=True) if content_tag else None
            # 발행일
            date_tag = soup.select_one("div.date span.input")
            published_at = None
            if date_tag:
                date_text = date_tag.get_text(strip=True)
                m = re.search(r"(\d{4}-\d{2}-\d{2} ?\d{2}:\d{2})", date_text)
                if m:
                    published_at = m.group(1)
            # 기자명
            reporter_tag = soup.select_one(".writer a")
            author = reporter_tag.get_text(strip=True) if reporter_tag else None
            # 대표 이미지
            img_tag = soup.select_one(".news_img img")
            image_url = None
            if img_tag:
                src = img_tag.get("src")
                if isinstance(src, list):
                    src = src[0] if src else None
                if src and isinstance(src, str) and src.startswith("//"):
                    image_url = "https:" + src
                elif src and isinstance(src, str):
                    image_url = src
            return {
                "title": title,
                "content_full": content,
                "published_at": published_at,
                "author": author,
                "image_url": image_url
            }
        except Exception as e:
            logger.debug(f"상세 기사 추출 실패: {url} - {str(e)}")
            return None

    async def crawl_all_categories(self) -> List[Dict[str, Any]]:
        await self._get_media_info()
        all_articles: List[Dict[str, Any]] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for category in self.CATEGORY_URLS.keys():
                articles = await self.crawl_category(browser, category)
                all_articles.extend(articles)
            await browser.close()
        return all_articles

    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mbc_articles_{today}.jsonl"
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        filepath = raw_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False) + '\n')
        return str(filepath)

    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        try:
            article_models = [dict_to_article(a) for a in articles]
            saved_count = await self.article_service.save_articles(article_models)
            return saved_count
        except Exception as e:
            logger.error(f"데이터베이스 저장 실패: {e}")
            raise

async def main():
    try:
        import os
        config = CrawlerConfig()
        crawler = MbcCrawler(config)
        crawler.ui.print_header()
        articles = await crawler.crawl_all_categories()
        if articles:
            filepath = await crawler.save_articles(articles)
            if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"):
                print("\n💾 데이터베이스에 저장 중...")
                try:
                    saved_count = await crawler.save_articles_to_db(articles)
                    print(f"✅ {saved_count}개 기사가 데이터베이스에 저장되었습니다.")
                except Exception as e:
                    print(f"❌ 데이터베이스 저장 실패: {e}")
                    print("   파일 저장은 완료되었습니다.")
            else:
                print("\n⚠️  데이터베이스 저장을 건너뜁니다. (환경변수 미설정)")
            crawler.ui.print_summary(len(articles), filepath)
        else:
            print("❌ 크롤링된 기사가 없습니다.")
    except Exception as e:
        logger.error(f"크롤링 실패: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 