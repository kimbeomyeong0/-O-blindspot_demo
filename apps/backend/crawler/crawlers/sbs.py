import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

import aiofiles
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
from bs4 import Tag

# Supabase 연동을 위한 import
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.theme import Theme

console = Console(theme=Theme({
    "success": "bold green",
    "fail": "bold red",
    "info": "bold cyan"
}))

def print_status(msg, status="info"):
    console.print(msg, style=status)

# 로깅 설정 - 파일과 콘솔 분리
def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "crawler_detailed.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    file_handler.setFormatter(file_formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])

setup_logging()
logger = logging.getLogger(__name__)

class Category(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class CrawlerConfig:
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 10
    min_title_length: int = 5

# --- 공통 유틸: 언론사명으로 media_id, bias 안전하게 가져오기 ---
import requests, os

def get_media_info(media_name: str):
    default_map = {
        'SBS 뉴스': {
            'media_id': '89b042ea-a01e-496c-9386-392a634885c6',
            'bias': 'center',
        },
    }
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    if SUPABASE_URL and SUPABASE_KEY:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        url = f"{SUPABASE_URL}/rest/v1/media_outlets?name=eq.{media_name}"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200 and resp.json():
                media = resp.json()[0]
                media_id = media.get("id") or default_map.get(media_name, {}).get("media_id", "")
                bias = media.get("bias") or default_map.get(media_name, {}).get("bias", "")
                return media_id, bias
        except Exception:
            pass
    d = default_map.get(media_name, {})
    return d.get("media_id", ""), d.get("bias", "")

class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 SBS 경제 크롤러 시작")
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

class ArticleExtractor:
    def __init__(self, config: CrawlerConfig):
        self.config = config

    async def extract_article_content(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1000)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            # 제목
            title = None
            title_meta = soup.find('meta', attrs={'itemprop': 'headline'})
            if title_meta:
                title = title_meta.get('content')
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)
            # 본문
            content = ""
            content_div = soup.find('div', class_='article')
            if not content_div:
                content_div = soup.find('div', class_='text_area')
            if content_div:
                content = content_div.get_text(separator='\n', strip=True)
            # 발행일
            published_at = None
            date_meta = soup.find('meta', attrs={'itemprop': 'datePublished'})
            if date_meta:
                published_at = date_meta.get('content')
            if not published_at:
                date_span = soup.find('span', class_='date')
                if date_span:
                    published_at = date_span.get_text(strip=True)
            # 기자명
            author = None
            author_em = soup.find('em', class_='name')
            if author_em:
                author = author_em.get_text(strip=True)
            # 이미지
            image_url = None
            image_meta = soup.find('meta', attrs={'itemprop': 'image'})
            if image_meta:
                image_url = image_meta.get('content')
            # 누락 필드는 None
            return {
                "title": title or None,
                "url": url,
                "content_full": content or None,
                "published_at": published_at or None,
                "author": author or None,
                "image_url": image_url or None
            }
        except Exception as e:
            logger.debug(f"기사 추출 실패 {url}: {str(e)}")
            return None

class SBSCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://news.sbs.co.kr/news/newsSection.do?sectionType=02&plink=GNB&cooper=SBSNEWS"
    }
    def __init__(self, config: CrawlerConfig):
        super().__init__()
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
        self.visited_urls = set()

    async def _extract_article_links(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        articles = []
        ul = soup.find('ul', attrs={'itemscope': True, 'itemtype': 'https://schema.org/ItemList'})
        if not ul or not isinstance(ul, Tag):
            return articles
        for li in ul.find_all('li', attrs={'itemprop': 'itemListElement'}):
            if not isinstance(li, Tag):
                continue
            try:
                span = li.find('span', attrs={'itemprop': 'item'})
                if not span or not isinstance(span, Tag):
                    continue
                url = None
                image_url = None
                published_at = None
                title = None
                # URL
                link = span.find('link', attrs={'itemprop': 'url'})
                if isinstance(link, Tag):
                    url = link.get('href')
                else:
                    url = None
                # 이미지
                image_meta = span.find('meta', attrs={'itemprop': 'image'})
                if isinstance(image_meta, Tag):
                    image_url = image_meta.get('content')
                else:
                    image_url = None
                # 발행일
                date_meta = span.find('meta', attrs={'itemprop': 'datePublished'})
                if isinstance(date_meta, Tag):
                    published_at = date_meta.get('content')
                else:
                    published_at = None
                # 제목
                title_meta = span.find('meta', attrs={'itemprop': 'headline'})
                if isinstance(title_meta, Tag):
                    title = title_meta.get('content')
                else:
                    title = None
                # 기자명(리스트에선 em.name)
                author = None
                em_name = li.find('em', class_='name')
                if em_name and isinstance(em_name, Tag):
                    author = em_name.get_text(strip=True)
                if url:
                    articles.append({
                        "url": url,
                        "title": title,
                        "image_url": image_url,
                        "published_at": published_at,
                        "author": author
                    })
            except Exception:
                continue
        return articles

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        base_url = self.CATEGORY_URLS[category]
        articles: List[Dict[str, Any]] = []
        seen_urls = set()
        page_idx = 1
        success, fail, skip = 0, 0, 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"기사 추출 중...", total=self.config.articles_per_category)
            while len(articles) < self.config.articles_per_category:
                # 페이지 URL 패턴 분기
                if page_idx == 1:
                    url = base_url
                else:
                    # 2페이지 이상: pageIdx, pageDate 필요(오늘 날짜)
                    today = datetime.now().strftime("%Y%m%d")
                    url = f"https://news.sbs.co.kr/news/newsSection.do?pageIdx={page_idx}&sectionType=02&pageDate={today}"
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                    await page.wait_for_timeout(1000)
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    list_articles = await self._extract_article_links(soup)
                    if not list_articles:
                        break
                    for item in list_articles:
                        if len(articles) >= self.config.articles_per_category:
                            break
                        article_url = item["url"]
                        if article_url in seen_urls:
                            skip += 1
                            continue
                        seen_urls.add(article_url)
                        # 상세 파싱
                        detail = await self.extractor.extract_article_content(page, article_url)
                        if detail and detail.get("title") and detail.get("content_full"):
                            # 필드 보정
                            detail["category"] = category.value
                            detail["image_url"] = item.get("image_url") or detail.get("image_url")
                            detail["published_at"] = item.get("published_at") or detail.get("published_at")
                            detail["author"] = item.get("author") or detail.get("author")
                            articles.append(detail)
                            success += 1
                            progress.update(task, advance=1, description=f"성공 {success} | 실패 {fail} | 스킵 {skip}")
                        else:
                            fail += 1
                            progress.update(task, description=f"성공 {success} | 실패 {fail} | 스킵 {skip}")
                    page_idx += 1
                except Exception as e:
                    logger.warning(f"페이지 파싱 실패: {url} | {e}")
                    break
                finally:
                    await page.close()
        return articles

    async def crawl_all_categories(self, test_mode: bool = False) -> List[Dict[str, Any]]:
        ConsoleUI.print_header()
        all_articles = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for category in Category:
                    ConsoleUI.print_category_start(category.value)
                    articles = await self.crawl_category(browser, category)
                    all_articles.extend(articles)
                    ConsoleUI.print_category_complete(category.value, len(articles))
                    if test_mode:
                        break
            finally:
                await browser.close()
        return all_articles

    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return ""
        data_dir = Path("data/raw")
        data_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sbs_articles_{timestamp}.jsonl"
        filepath = data_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False) + '\n')
        return str(filepath)

    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return 0
        try:
            article_objects = []
            media_id, bias = get_media_info('SBS 뉴스')
            for article_data in articles:
                article = Article(
                    title=article_data.get('title', ''),
                    url=article_data.get('url', ''),
                    category=article_data.get('category', ''),
                    content_full=article_data.get('content_full', ''),
                    published_at=None,  # 실제 변환 필요
                    author=article_data.get('author', ''),
                    image_url=article_data.get('image_url', ''),
                    media_id=media_id,
                    bias=bias
                )
                article_objects.append(article)
            saved_count = await self.article_service.save_articles(article_objects)
            return saved_count
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
            return 0

async def main():
    config = CrawlerConfig()
    crawler = SBSCrawler(config)
    media_id, bias = get_media_info('SBS 뉴스')
    articles = await crawler.crawl_all_categories()
    if articles:
        for article in articles:
            article["media_id"] = media_id
            article["bias"] = bias
        filepath = await crawler.save_articles(articles)
        await crawler.save_articles_to_db(articles)
        ConsoleUI.print_summary(len(articles), filepath)
    else:
        print("크롤링된 기사가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main()) 