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

# Supabase 연동 import
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

# 로깅 설정
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler(log_dir / "crawler_detailed.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class Category(Enum):
    ECONOMY = "경제"

@dataclass
class CrawlerConfig:
    # max_pages: int = 2  # 페이지 제한 없음, 필요시 복구
    articles_per_category: int = 30  # 실전 테스트를 위해 30개로 명시
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 30
    min_title_length: int = 10
    # 경향신문용 셀렉터
    list_selector: str = 'div.list ul#recentList > li > article > div > a'
    title_selector: str = 'article > header > h1'
    content_selector: str = 'section.art_cont div.art_body#articleBody'
    date_selector: str = 'article > header > div.date > p'
    author_selector: str = 'article > header > ul.bottom > li.editor > a'
    image_selector: str = 'section.art_cont div.art_body#articleBody img'

class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 경향신문 크롤러 시작")
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
            await page.wait_for_timeout(1500)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            # 제목
            title = soup.select_one(self.config.title_selector)
            title = title.get_text(strip=True) if title else None
            if not title or len(title) < self.config.min_title_length:
                logger.debug(f"제목 없음: {url}")
                return None
            # 본문
            content = ''
            content_area = soup.select_one(self.config.content_selector)
            if content_area:
                # 광고/배너 등 불필요 태그 제거
                for tag in content_area.find_all(['script', 'style', 'iframe', 'div', 'aside', 'footer', 'form', 'nav', 'button', 'noscript', 'svg', 'figure', 'figcaption', 'ins', 'ul', 'li'], recursive=True):
                    tag.decompose()
                content = '\n'.join([p.get_text(" ", strip=True) for p in content_area.find_all(['p', 'span'])])
            if not content or len(content.strip()) < self.config.min_content_length:
                logger.debug(f"본문 없음: {url}")
                return None
            # 발행일
            date = soup.select_one(self.config.date_selector)
            published_at = None
            if date:
                date_text = date.get_text(strip=True)
                # '입력 2025.07.14 18:00' 등에서 날짜만 추출
                m = re.search(r'(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2})', date_text)
                if m:
                    published_at = datetime.strptime(m.group(1), "%Y.%m.%d %H:%M").isoformat()
            # 혹시라도 못 찾으면 전체 텍스트에서 한 번 더 시도
            if not published_at:
                all_text = soup.get_text()
                m = re.search(r'(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2})', all_text)
                if m:
                    published_at = datetime.strptime(m.group(1), "%Y.%m.%d %H:%M").isoformat()
            # 기자명
            author = soup.select_one(self.config.author_selector)
            author = author.get_text(strip=True) if author else ''
            # 이미지
            image = soup.select_one(self.config.image_selector)
            image_url = image['src'] if image and image.has_attr('src') else ''
            return {
                "title": title,
                "url": url,
                "content_full": content,
                "published_at": published_at or datetime.now().isoformat(),
                "author": author,
                "image_url": image_url
            }
        except Exception as e:
            logger.debug(f"기사 추출 실패 {url}: {str(e)}")
            return None

# --- 공통 유틸: 언론사명으로 media_id, bias 안전하게 가져오기 ---
import requests, os

def get_media_info(media_name: str):
    default_map = {
        '경향신문': {
            'media_id': '4a870e44-6fb5-467f-b236-da3687affbff',
            'bias': 'left',
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

class KhanCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://www.khan.co.kr/economy"
    }
    def __init__(self, config: CrawlerConfig):
        super().__init__()
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
        self.visited_urls = set()

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        category_base_url = self.CATEGORY_URLS[category]
        articles = []
        page = await browser.new_page()
        try:
            page_num = 1
            while len(articles) < self.config.articles_per_category:
                list_url = f"{category_base_url}?page={page_num}" if page_num > 1 else category_base_url
                await page.goto(list_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                # 기사 리스트가 로드될 때까지 명시적으로 대기
                try:
                    await page.wait_for_selector(self.config.list_selector, timeout=5000)
                except Exception:
                    logger.warning(f"기사 리스트 로드 실패: {list_url}")
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                article_links = []
                for a in soup.select(self.config.list_selector):
                    href = a.get('href')
                    if isinstance(href, list):
                        href = href[0] if href else None
                    if href and isinstance(href, str):
                        if href.startswith('/'):
                            href = f'https://www.khan.co.kr{href}'
                        if href.startswith('http') and href not in self.visited_urls:
                            article_links.append(href)
                            self.visited_urls.add(href)
                if not article_links:
                    # 디버깅용: HTML 저장
                    with open(f"debug_khan_page_{page_num}.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    break  # 더 이상 기사가 없으면 종료
                for url in article_links:
                    if len(articles) >= self.config.articles_per_category:
                        break
                    article_data = await self.extractor.extract_article_content(page, url)
                    if article_data:
                        article_data['category'] = category.value
                        article_data['source'] = '경향신문'
                        articles.append(article_data)
                        print_status(f"✔ {article_data['title'][:40]} ... 성공", "success")
                    else:
                        print_status(f"✖ {url} ... 본문 없음", "fail")
                page_num += 1
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
        filename = f"khan_articles_{timestamp}.jsonl"
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
            for article_data in articles:
                media_id, bias = get_media_info('경향신문')
                article = Article(
                    title=article_data.get('title', ''),
                    url=article_data.get('url', ''),
                    category=article_data.get('category', ''),
                    content_full=article_data.get('content_full', ''),
                    published_at=None,
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
    crawler = KhanCrawler(config)
    media_id, bias = get_media_info('경향신문')
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
