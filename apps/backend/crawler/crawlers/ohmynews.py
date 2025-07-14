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

# Supabase 연동을 위한 import
import sys
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.theme import Theme
from rich.live import Live
from rich.spinner import Spinner

console = Console(theme=Theme({
    "success": "bold green",
    "fail": "bold red",
    "info": "bold cyan"
}))

def print_status(msg, status="info"):
    console.print(msg, style=status)

# 로깅 설정 - 파일과 콘솔 분리
def setup_logging():
    """로깅 설정을 초기화합니다."""
    # 로그 디렉토리 생성
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 파일 로거 (상세 정보)
    file_handler = logging.FileHandler(log_dir / "crawler_detailed.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    
    # 콘솔 로거 (간단한 정보만)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    
    # 루트 로거 설정
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler]
    )

setup_logging()
logger = logging.getLogger(__name__)

# 외부 noisy 라이브러리 로깅 레벨 최소화
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("supabase").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

class Category(Enum):
    """크롤링할 카테고리 정의"""
    ECONOMY = "경제"

@dataclass
class CrawlerConfig:
    """크롤러 설정 클래스"""
    max_pages: int = 2  # 30개 기사를 위해 2페이지 (1페이지당 20개)
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 5  # 테스트를 위해 완화
    min_title_length: int = 10
    
    # CSS 셀렉터들 - 오마이뉴스에 맞게 보강
    headline_selector: str = '.list_article a'
    title_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None
    date_selectors: Optional[List[str]] = None
    author_selectors: Optional[List[str]] = None
    image_selectors: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.title_selectors is None:
            self.title_selectors = ['h1', '.article-title', '.story-title', '.title']
        if self.content_selectors is None:
            self.content_selectors = [
                'div#article_view', 'div.article_view', '.article_view', '#article_view',
                '.content', '.article_content', '.news_body', '.view_content', '.view',
                '.article-body', '.news-article-body', '.story-content', '.entry-content',
                '#article-body', '.article-content', '.text-content', '.content-body',
                '.article-text', '.story-body'
            ]
        if self.date_selectors is None:
            self.date_selectors = [
                "meta[property='article:published_time']", 
                "meta[property='og:article:published_time']", 
                "time", ".published-date", ".article-date", ".date"
            ]
        if self.author_selectors is None:
            self.author_selectors = [
                "meta[property='og:article:author']", 
                ".author", ".byline", ".writer", ".reporter", ".writer_name"
            ]
        if self.image_selectors is None:
            self.image_selectors = [
                "meta[property='og:image']", 
                "meta[property='twitter:image']", 
                ".article-image img", ".story-image img", ".article_img img"
            ]

# 기존 ConsoleUI 클래스는 rich 기반으로 대체
class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 오마이뉴스 크롤러 시작")
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
    """기사 내용 추출 클래스"""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
    
    async def extract_article_content(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """기사 내용을 추출합니다."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            # 본문이 로드될 때까지 대기
            try:
                await page.wait_for_selector('.at_contents', timeout=5000)
            except Exception:
                pass  # 셀렉터가 없으면 그냥 진행
            await page.wait_for_timeout(2000)
            
            html = await page.content()
            # 디버깅용 HTML 저장
            with open("debug_ohmynews.html", "w", encoding="utf-8") as f:
                f.write(html)
            soup = BeautifulSoup(html, 'html.parser')
            
            # 제목 추출
            title = self._extract_title(soup)
            if not title:
                logger.debug(f"제목을 찾을 수 없습니다: {url}")
                return None
            
            # 본문 추출
            content = self._extract_content(soup)
            if not content or len(content.strip()) < self.config.min_content_length:
                logger.warning(f"본문 추출 실패: {url} | 제목: {title}")
                return None
            
            # 메타데이터 추출
            published_at = self._extract_published_date(soup)
            author = self._extract_author(soup)
            image_url = self._extract_image_url(soup)
            
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
    
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """오마이뉴스 기사 제목을 추출합니다."""
        # 오마이뉴스 제목 셀렉터들 (우선순위 순)
        title_selectors = [
            'h2.article_tit a',  # 오마이뉴스 메인 제목
            'h2.article_tit',    # 제목 영역
            'h1.article_tit a',  # h1 제목
            'h1.article_tit',    # h1 제목 영역
            '.article_tit a',     # 제목 링크
            '.article_tit',       # 제목 영역
            'h1',                 # 일반 h1
            'h2',                 # 일반 h2
            '.title',             # 일반 제목
        ]
        
        for selector in title_selectors:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                if title and len(title) >= self.config.min_title_length:
                    return title
        
        # 기존 title_selectors도 fallback으로 사용
        if self.config.title_selectors is not None:
            for selector in self.config.title_selectors:
                el = soup.select_one(selector)
                if el:
                    title = el.get_text(strip=True)
                    if title and len(title) >= self.config.min_title_length:
                        return title
        
        return None
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """오마이뉴스 기사 본문을 추출합니다."""
        content_parts = []
        
        # .at_contents가 있으면 우선 사용 (오마이뉴스 본문 영역)
        at_contents = soup.select_one('.at_contents')
        if at_contents:
            # 불필요한 태그들 제거
            unwanted_selectors = [
                'figure.omn-photo',  # 이미지
                'script',            # 스크립트
                'style',             # 스타일
                'iframe',            # iframe
                'div[id^="dv"]',     # 광고 div (dv로 시작하는 id)
                'div[id^="google_ads"]',  # 구글 광고
                'div[class*="ad"]',  # 광고 클래스
                'div[class*="advertisement"]',  # 광고 클래스
                'div[class*="V0"]',  # 광고 클래스
                'div[class*="ohmynews_article"]',  # 광고 클래스
                'div[id*="CenterAd"]',  # 중앙 광고
                'div[class*="livere"]',  # 댓글 시스템
                'div[class*="dable"]',   # Dable 위젯
                'div[class*="gallery"]', # 갤러리
                'div[class*="reporter"]', # 기자 정보
                'div[class*="copyright"]', # 저작권
                'div[class*="tag_area"]', # 태그 영역
                'div[class*="arc-bottom"]', # 하단 영역
                'div[class*="support-box"]', # 지원 박스
                'div[class*="layer"]', # 레이어
                'div[class*="ad_area"]', # 광고 영역
            ]
            
            for selector in unwanted_selectors:
                for unwanted in at_contents.select(selector):
                    unwanted.decompose()
            
            # <br> 태그를 줄바꿈으로 변환
            for br in at_contents.find_all("br"):
                br.replace_with("\n")
            
            # 텍스트 추출
            text = at_contents.get_text(separator="\n", strip=True)
            
            # 빈 줄 정리 및 텍스트 정리
            lines = []
            for line in text.splitlines():
                line = line.strip()
                if line and len(line) > 1:  # 빈 줄이 아니고 1글자보다 긴 경우만
                    lines.append(line)
            
            if lines:
                content_parts.append("\n".join(lines))
        
        # .at_contents가 없거나 내용이 부족한 경우 기존 content_selectors 사용
        if not content_parts and self.config.content_selectors is not None:
            for selector in self.config.content_selectors:
                elements = soup.select(selector)
                for element in elements:
                    # 불필요한 태그 제거
                    for unwanted in element.find_all(['script', 'style', 'iframe', 'figure']):
                        unwanted.decompose()
                    
                    text = element.get_text(separator="\n", strip=True)
                    if text and len(text) > 10:  # 최소 길이 체크
                        content_parts.append(text)
        
        return '\n\n'.join(content_parts) if content_parts else ""
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        """오마이뉴스 기사 발행일을 추출합니다."""
        # 오마이뉴스 날짜 셀렉터들
        date_selectors = [
            '.atc-sponsor .date',  # 오마이뉴스 날짜
            '.atc-sponsor span.date', # 날짜 span
            '.info-list .date',    # 정보 영역 날짜
            '.article-info .date',  # 기사 정보 날짜
            '.published-date',      # 발행일
            '.article-date',        # 기사 날짜
            '.date',               # 일반 날짜
        ]
        
        for selector in date_selectors:
            el = soup.select_one(selector)
            if el:
                date_str = el.get_text(strip=True)
                if date_str:
                    # 날짜 형식 정리 (예: "25.07.14 15:48" -> "2025-07-14T15:48:00")
                    date_str = re.sub(r'[^\d\.\-\s:]', '', str(date_str)).strip()
                    if date_str:
                        # 오마이뉴스 날짜 형식 변환 (25.07.14 -> 2025-07-14)
                        if re.match(r'\d{2}\.\d{2}\.\d{2}', date_str):
                            parts = date_str.split('.')
                            if len(parts) >= 3:
                                year = f"20{parts[0]}"
                                month = parts[1]
                                day = parts[2]
                                date_str = f"{year}-{month}-{day}"
                        return date_str
        
        # 기존 date_selectors도 fallback으로 사용
        if self.config.date_selectors is not None:
            for selector in self.config.date_selectors:
                el = soup.select_one(selector)
                if el:
                    if selector.startswith('meta'):
                        date_str = el.get('content', '')
                    else:
                        date_str = el.get_text(strip=True)
                    
                    if date_str:
                        # 날짜 형식 정리
                        date_str = re.sub(r'[^\d\-\s:]', '', str(date_str)).strip()
                        if date_str:
                            return date_str
        
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """오마이뉴스 기사 작성자를 추출합니다."""
        # 오마이뉴스 작성자 셀렉터들
        author_selectors = [
            '.info-list strong',  # 기자명 (strong 태그)
            '.info-list a strong', # 기자명 링크 내부
            '.lk_my strong',       # 기자 링크
            '.reporter strong',    # 기자 정보
            '.writer strong',      # 작성자
            '.author strong',      # 저자
            '.byline strong',      # 바이라인
            '.info-list .tt01',    # 기자 ID
            '.lk_my .tt01',        # 기자 ID
            '.reporter .tt01',     # 기자 ID
        ]
        
        for selector in author_selectors:
            el = soup.select_one(selector)
            if el:
                author = el.get_text(strip=True)
                if author and len(author) > 1:
                    return author
        
        # 기존 author_selectors도 fallback으로 사용
        if self.config.author_selectors is not None:
            for selector in self.config.author_selectors:
                el = soup.select_one(selector)
                if el:
                    if selector.startswith('meta'):
                        author = el.get('content', '')
                    else:
                        author = el.get_text(strip=True)
                    
                    if author and len(str(author)) > 1:
                        return str(author)
        
        return None
    
    def _extract_image_url(self, soup: BeautifulSoup) -> Optional[str]:
        """이미지 URL을 추출합니다."""
        if self.config.image_selectors is None:
            return None
            
        for selector in self.config.image_selectors:
            el = soup.select_one(selector)
            if el:
                if selector.startswith('meta'):
                    image_url = el.get('content', '')
                else:
                    image_url = el.get('src', '')
                
                if image_url and str(image_url).startswith('http'):
                    return str(image_url)
        return None

# 기존 코드(ArticleExtractor, CrawlerConfig 등)는 그대로 유지

# 기사별 처리에 rich Progress 적용
from contextlib import contextmanager

@contextmanager
def rich_spinner(msg: str):
    with Live(Spinner("dots", text=msg), refresh_per_second=10, console=console):
        yield

class OhmynewsCrawler(BaseNewsCrawler):
    """오마이뉴스 크롤러 클래스"""
    
    CATEGORY_URLS = {
        Category.ECONOMY: "https://www.ohmynews.com/NWS_Web/ArticlePage/Total_Article.aspx?PAGE_CD=C0300"
    }
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
    
    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        """특정 카테고리를 크롤링합니다."""
        articles = []
        url = self.CATEGORY_URLS[category]
        
        page = await browser.new_page()
        try:
            for page_num in range(1, self.config.max_pages + 1):
                if page_num == 1:
                    page_url = url
                else:
                    page_url = f"{url}&pageno={page_num}"
                # [DEBUG] 페이지 이동 로그 (URL만 남기고 기사 URL 리스트 출력은 제거)
                await page.goto(page_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await page.wait_for_timeout(self.config.wait_timeout)
                
                # 기사 링크 추출
                links_and_titles = await self._extract_article_links(page, category)
                # (기사 URL 리스트 출력 제거)
                
                if not links_and_titles:
                    logger.warning(f"페이지 {page_num}에서 기사 링크를 찾을 수 없습니다.")
                    break
                
                # 기사 내용 추출
                page_articles = await self._extract_articles(page, category, links_and_titles)
                articles.extend(page_articles)
                
                # 목표 기사 수에 도달하면 중단
                if len(articles) >= self.config.articles_per_category:
                    articles = articles[:self.config.articles_per_category]
                    break
                
                logger.info(f"페이지 {page_num}: {len(page_articles)}개 기사 수집")
        
        finally:
            await page.close()
        
        return articles
    
    async def _extract_article_links(self, page: Page, category: Category) -> List[Tuple[str, str]]:
        """기사 링크와 제목을 추출합니다."""
        try:
            # 상단 주요 기사와 일반 기사 모두 포함
            article_elements = await page.query_selector_all(
                'div.top_news a, ul.list_type1 dt > a'
            )
            
            links_and_titles = []
            for element in article_elements:
                try:
                    href = await element.get_attribute('href')
                    title = await element.text_content()
                    # 실제 기사 본문 링크만 추출
                    if href and '/NWS_Web/View/at_pg.aspx?CNTN_CD=' in href:
                        if href.startswith('/'):
                            href = f"https://www.ohmynews.com{href}"
                        if href and title:
                            links_and_titles.append((href.strip(), title.strip()))
                except Exception as e:
                    logger.debug(f"기사 링크 추출 실패: {str(e)}")
                    continue
            
            return links_and_titles
            
        except Exception as e:
            logger.error(f"기사 링크 추출 중 오류: {str(e)}")
            return []
    
    async def _extract_articles(self, page: Page, category: Category, links_and_titles: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        articles = []
        total = len(links_and_titles)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"기사 추출 중...", total=total)
            for i, (url, title) in enumerate(links_and_titles, 1):
                progress.update(task, advance=1, description=f"({i}/{total}) {title[:30]}")
                try:
                    article_data = await self.extractor.extract_article_content(page, url)
                    if article_data:
                        article_data['category'] = category.value
                        article_data['source'] = '오마이뉴스'
                        articles.append(article_data)
                        print_status(f"✔ {title[:40]} ... 성공", "success")
                    else:
                        print_status(f"✖ {title[:40]} ... 본문 없음", "fail")
                    await page.wait_for_timeout(100)
                except Exception as e:
                    print_status(f"✖ {title[:40]} ... 오류: {e}", "fail")
                    continue
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
                    # (임시 제한 해제) 전체 기사 사용
                    all_articles.extend(articles)
                    ConsoleUI.print_category_complete(category.value, len(articles))
                    
                    if test_mode:
                        break
            
            finally:
                await browser.close()
        
        return all_articles
    
    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        """기사를 JSONL 파일로 저장합니다."""
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return ""
        
        # 데이터 디렉토리 생성
        data_dir = Path("data/raw")
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ohmynews_articles_{timestamp}.jsonl"
        filepath = data_dir / filename
        
        # JSONL 형식으로 저장
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False) + '\n')
        
        return str(filepath)
    
    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        """기사를 데이터베이스에 저장합니다."""
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return 0
        try:
            # Article 모델로 변환
            article_objects = []
            for article_data in articles:
                try:
                    bias = article_data.get('bias', '') or 'left'
                    article = Article(
                        title=article_data.get('title', ''),
                        url=article_data.get('url', ''),
                        category=article_data.get('category', ''),
                        content_full=article_data.get('content_full', ''),
                        published_at=None,  # 문자열 대신 None으로 설정
                        author=article_data.get('author', ''),
                        image_url=article_data.get('image_url', ''),
                        media_id=article_data.get('media_id', '') or '',
                        bias=bias
                    )
                    article_objects.append(article)
                except Exception as e:
                    continue
            # 데이터베이스에 저장
            saved_count = await self.article_service.save_articles(article_objects)
            return saved_count
        except Exception as e:
            return 0

# --- 공통 유틸: 언론사명으로 media_id 안전하게 가져오기 ---
import requests, os

def get_media_info(media_name: str):
    # 오마이뉴스 등 주요 언론사 기본값 사전
    default_map = {
        '오마이뉴스': {
            'media_id': '149dab80-d623-49d7-a0f2-4c52329d2626',  # DB와 일치하도록 수정
            'bias': 'left',
        },
        # 필요시 다른 언론사도 추가
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
        except Exception as e:
            pass
    d = default_map.get(media_name, {})
    return d.get("media_id", ""), d.get("bias", "")

# --- main 함수에서 공통 유틸 사용 ---
async def main():
    """메인 실행 함수"""
    config = CrawlerConfig()
    crawler = OhmynewsCrawler(config)

    # 공통 유틸로 media_id 조회
    media_id, bias = get_media_info('오마이뉴스')
    # print(f"[DEBUG] 최종 사용 media_id: {media_id}")  # 불필요한 디버그 출력 제거

    # 크롤링 실행
    articles = await crawler.crawl_all_categories()

    if articles:
        # 각 기사에 media_id, bias 할당 (없으면 안전한 기본값)
        for article in articles:
            article["media_id"] = media_id or '149dab80-d623-49d7-a0f2-4c52329d2626'
            article["bias"] = bias or 'left'
        # 파일로 저장
        filepath = await crawler.save_articles(articles)
        # 데이터베이스에 저장
        await crawler.save_articles_to_db(articles)
        # 결과 출력
        ConsoleUI.print_summary(len(articles), filepath)
    else:
        print("크롤링된 기사가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
