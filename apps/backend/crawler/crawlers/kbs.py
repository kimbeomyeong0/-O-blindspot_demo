import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any, cast
from dataclasses import dataclass
from enum import Enum

import aiofiles
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page

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
    ECONOMY = ("경제", "0004")
    # 추후 확장 가능
    # POLITICS = ("정치", "0001")
    # ...
    def __init__(self, label, code):
        self.label = label
        self.code = code

@dataclass
class CrawlerConfig:
    max_pages: int = 20  # 넉넉히
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 1  # 본문 길이 제한 완화
    min_title_length: int = 5

class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 KBS 크롤러 시작")
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
        self.fail_html_count = 0  # 실패 HTML 저장 개수 제한

    async def extract_article_content(self, page: Page, url: str, fail_idx: int = 0) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1500)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            # 제목
            title = self._extract_title(soup)
            if not title:
                logger.debug(f"제목 없음: {url}")
                print_status(f"✖ 제목 없음: {url}", "fail")
                return None
            # 본문
            content = self._extract_content(soup)
            if not content or len(content.strip()) < self.config.min_content_length:
                logger.warning(f"본문 없음: {url}")
                print_status(f"⚠ 본문 없음: {url}", "fail")
                # 실패 HTML 최대 5개까지만 저장
                if self.fail_html_count < 5:
                    with open(f"debug_kbs_fail_{self.fail_html_count+1}.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    self.fail_html_count += 1
                # 본문이 없어도 기사 저장 (빈 문자열)
                content = ""
            # 발행일
            published_at = self._extract_published_date(soup)
            # 기자명/이메일
            journalist, journalist_email = self._extract_journalist(soup)
            # 대표 이미지
            image_url = self._extract_image_url(soup)
            return {
                "title": title,
                "url": url,
                "content_full": content,
                "published_at": published_at or datetime.now().isoformat(),
                "journalist": journalist,
                "journalist_email": journalist_email,
                "image_url": image_url
            }
        except Exception as e:
            logger.debug(f"상세 페이지 접근 실패 {url}: {str(e)}")
            print_status(f"✖ 상세 페이지 접근 실패: {url}", "fail")
            return None

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        el = soup.select_one('h4.headline-title')
        if el:
            return el.get_text(strip=True)
        return None

    def _extract_content(self, soup: BeautifulSoup) -> str:
        el = soup.select_one('div.detail-body#cont_newstext')
        if el:
            # <br> 태그를 줄바꿈으로 변환
            for br in el.find_all("br"):
                br.replace_with("\n")
            return el.get_text(separator=" ", strip=True)
        return ""

    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        el = soup.select_one('em.input-date')
        if el:
            # '입력 2025.07.14 (19:35)' 형식
            text = el.get_text(strip=True)
            m = re.search(r'(\d{4}\.\d{2}\.\d{2}) \((\d{2}:\d{2})\)', text)
            if m:
                dt_str = f"{m.group(1)} {m.group(2)}"
                try:
                    return datetime.strptime(dt_str, "%Y.%m.%d %H:%M").isoformat()
                except Exception:
                    return None
        return None

    def _extract_journalist(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
        # 1순위: 상세 영역
        el = soup.select_one('span.reporter-name')
        if el:
            name = el.get_text(strip=True)
            email = None
            parent = el.find_parent() if el else None
            mail_btn = parent.find('a', href=re.compile(r'^mailto:')) if parent else None
            if mail_btn:
                email = mail_btn.get_text(strip=True)
            return name, email
        # 2순위: 프린트 영역
        el2 = soup.select_one('div.news-writer p.name')
        if el2:
            name = el2.get_text(strip=True)
            email = None
            mail_btn = el2.find('a', href=re.compile(r'^mailto:'))
            if mail_btn:
                email = mail_btn.get_text(strip=True)
            return name, email
        return None, None

    def _extract_image_url(self, soup: BeautifulSoup) -> Optional[str]:
        el = soup.select_one('div.detail-visual img')
        if el and el.has_attr('src'):
            src = el['src']
            if isinstance(src, list):
                return src[0] if src else None
            return src
        # 프린트 영역
        el2 = soup.select_one('div.view_con_img img')
        if el2 and el2.has_attr('src'):
            src2 = el2['src']
            if isinstance(src2, list):
                return src2[0] if src2 else None
            return src2
        return None

    def _extract_category(self, soup: BeautifulSoup) -> Optional[str]:
        return None

class KbsCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://news.kbs.co.kr/news/list.do?ctcd=0004"
    }
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
        self.ui = ConsoleUI()

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        articles = []
        seen_urls = set()
        # 오늘 날짜를 YYYYMMDD 형식으로
        from datetime import datetime
        date = datetime.now().strftime("%Y%m%d")
        base_url = f"https://news.kbs.co.kr/news/pc/category/category.do?ctcd=0004&ref=pSiteMap"
        page = await browser.new_page()
        try:
            page_num = 1
            fail_idx = 0
            while len(articles) < self.config.articles_per_category:
                page_url = f"{base_url}#{date}&{page_num}"
                await page.goto(page_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await page.wait_for_timeout(self.config.wait_timeout)
                links_and_titles = await self._extract_article_links(page)
                if not links_and_titles:
                    break
                added_this_page = 0
                for url, title in links_and_titles:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    article = await self.extractor.extract_article_content(page, url, fail_idx)
                    if article:
                        article['category'] = '경제'
                        articles.append(article)
                        added_this_page += 1
                        if len(articles) >= self.config.articles_per_category:
                            break
                    else:
                        fail_idx += 1
                if added_this_page == 0:
                    # 이 페이지에서 기사가 하나도 추가되지 않으면 종료
                    break
                page_num += 1
        finally:
            await page.close()
        return articles

    async def _extract_article_links(self, page: Page) -> List[Tuple[str, str]]:
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        for a in soup.select('div.box-contents.has-wrap a.box-content.flex-style'):
            href_val = a.get('href')
            href = href_val if isinstance(href_val, str) else (href_val[0] if isinstance(href_val, list) and href_val and isinstance(href_val[0], str) else None)
            title_el = a.select_one('p.title')
            title = str(title_el.get_text(strip=True)) if title_el else ""
            if isinstance(href, str) and href and title:
                url = href if href.startswith('http') else f"https://news.kbs.co.kr{href}"
                links.append(cast(Tuple[str, str], (url, title)))
        return links

    async def crawl_all_categories(self, test_mode: bool = False) -> List[Dict[str, Any]]:
        self.ui.print_header()
        all_articles = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for category in Category:
                    self.ui.print_category_start(category.label)
                    articles = await self.crawl_category(browser, category)
                    all_articles.extend(articles)
                    self.ui.print_category_complete(category.label, len(articles))
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
        filename = f"kbs_articles_{timestamp}.jsonl"
        filepath = data_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False) + '\n')
        return str(filepath)

    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return 0
        # media_id, bias 자동 조회/생성
        for article in articles:
            media_info = await self.article_service.get_or_create_media("KBS 뉴스")
            print("media_info:", media_info)  # 디버깅
            article['media_id'] = media_info['id'] if media_info else None
            article['bias'] = media_info['bias'] if media_info and media_info['bias'] else 'center'
            print("article media_id:", article['media_id'], "bias:", article['bias'])  # 디버깅
        # Article 모델 변환
        article_objs = []
        for art in articles:
            try:
                published_at = art.get('published_at')
                if published_at and isinstance(published_at, str):
                    try:
                        published_at = datetime.fromisoformat(published_at)
                    except Exception:
                        published_at = None
                bias = art.get('bias', 'center') or 'center'
                article_objs.append(Article(
                    title=art.get('title', ''),
                    url=art.get('url', ''),
                    category=art.get('category', ''),
                    content_full=art.get('content_full', ''),
                    published_at=published_at,
                    author=art.get('journalist', ''),
                    image_url=art.get('image_url', ''),
                    media_id=art.get('media_id', None),
                    bias=bias
                ))
            except Exception:
                continue
        saved_count = await self.article_service.save_articles(article_objs)
        return saved_count

async def main():
    config = CrawlerConfig()
    crawler = KbsCrawler(config)
    articles = await crawler.crawl_all_categories(test_mode=False)
    if articles:
        filepath = await crawler.save_articles(articles)
        print_status(f"\n💾 파일 저장 완료: {filepath}", "success")
        try:
            saved_count = await crawler.save_articles_to_db(articles)
            print_status(f"✅ {saved_count}개 기사가 DB에 저장됨", "success")
        except Exception as e:
            print_status(f"❌ DB 저장 실패: {e}", "fail")
        crawler.ui.print_summary(len(articles), filepath)
    else:
        print_status("❌ 크롤링된 기사가 없습니다.", "fail")

if __name__ == "__main__":
    asyncio.run(main()) 