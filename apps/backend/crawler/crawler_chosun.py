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
from app.services.article_service import ArticleService
from app.models.article import Article
from crawler.base_crawler import BaseNewsCrawler

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

class Category(Enum):
    """크롤링할 카테고리 정의"""
    ECONOMY = "경제"
    POLITICS = "정치"
    NATIONAL = "사회"
    CULTURE = "문화"
    INTERNATIONAL = "국제"
    SPORTS = "스포츠"

@dataclass
class CrawlerConfig:
    """크롤러 설정 클래스"""
    max_more_clicks: int = 10
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10
    
    # CSS 셀렉터들
    headline_selector: str = 'a.story-card__headline'
    title_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None
    date_selectors: Optional[List[str]] = None
    author_selectors: Optional[List[str]] = None
    image_selectors: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.title_selectors is None:
            self.title_selectors = ['h1', '.article-title', '.story-title']
        if self.content_selectors is None:
            self.content_selectors = [
                '.article-body', '.news-article-body', '.story-content', 
                '.entry-content', '#article-body', '.article-content', 
                '.text-content', '.content-body', '.article-text', '.story-body'
            ]
        if self.date_selectors is None:
            self.date_selectors = [
                "meta[property='article:published_time']", 
                "meta[property='og:article:published_time']", 
                "time", ".published-date", ".article-date"
            ]
        if self.author_selectors is None:
            self.author_selectors = [
                "meta[property='og:article:author']", 
                ".author", ".byline", ".writer", ".reporter"
            ]
        if self.image_selectors is None:
            self.image_selectors = [
                "meta[property='og:image']", 
                "meta[property='twitter:image']", 
                ".article-image img", ".story-image img"
            ]

class ConsoleUI:
    """터미널 UI 관리 클래스"""
    
    @staticmethod
    def print_header():
        """크롤링 시작 헤더를 출력합니다."""
        print("\n" + "="*60)
        print("🚀 조선일보 크롤러 시작")
        print("="*60)
    
    @staticmethod
    def print_category_start(category: str):
        """카테고리 시작을 출력합니다."""
        print(f"\n📰 {category} 카테고리 크롤링 중...")
    
    @staticmethod
    def print_progress(category: str, current: int, target: int, total_articles: int):
        """진행 상황을 출력합니다."""
        progress = min(100, int(current / target * 100))
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        print(f"   {bar} {current}/{target} ({progress}%) - 총 {total_articles}개 기사")
    
    @staticmethod
    def print_category_complete(category: str, count: int):
        """카테고리 완료를 출력합니다."""
        print(f"✅ {category}: {count}개 기사 수집 완료")
    
    @staticmethod
    def print_summary(total_articles: int, filepath: str):
        """최종 요약을 출력합니다."""
        print("\n" + "="*60)
        print(f"🎉 크롤링 완료!")
        print(f"📊 총 {total_articles}개 기사 수집")
        print(f"💾 저장 위치: {filepath}")
        print("="*60 + "\n")

class ArticleExtractor:
    """기사 내용 추출 클래스"""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
    
    async def extract_article_content(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """기사 내용을 추출합니다."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(500)
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 제목 추출
            title = self._extract_title(soup)
            if not title:
                logger.debug(f"제목을 찾을 수 없습니다: {url}")
                return None
            
            # 본문 추출
            content = self._extract_content(soup)
            if not content or len(content.strip()) < self.config.min_content_length:
                logger.debug(f"본문을 찾을 수 없습니다: {url}")
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
        """제목을 추출합니다."""
        if self.config.title_selectors is None:
            return None
        for selector in self.config.title_selectors:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                if len(title) >= self.config.min_title_length:
                    return title
        return None
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """본문을 추출합니다."""
        if self.config.content_selectors is None:
            return ""
        for selector in self.config.content_selectors:
            el = soup.select_one(selector)
            if el:
                # 광고 및 불필요한 요소 제거
                for unwanted in el.select("script, style, .ad, .advertisement"):
                    unwanted.decompose()
                content = el.get_text(strip=True)
                if len(content) > 100:
                    return content
        return ""
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        """발행일을 추출합니다."""
        if self.config.date_selectors is None:
            return None
        for selector in self.config.date_selectors:
            if selector.startswith("meta"):
                meta = soup.select_one(selector)
                if meta:
                    content = meta.get("content")
                    if content and isinstance(content, str):
                        return content
            else:
                el = soup.select_one(selector)
                if el:
                    time_str = el.get("datetime") or el.get_text(strip=True)
                    if time_str and isinstance(time_str, str):
                        return time_str
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """작성자를 추출합니다."""
        if self.config.author_selectors is None:
            return None
        for selector in self.config.author_selectors:
            if selector.startswith("meta"):
                meta = soup.select_one(selector)
                if meta:
                    content = meta.get("content")
                    if content and isinstance(content, str):
                        return content
            else:
                el = soup.select_one(selector)
                if el:
                    return el.get_text(strip=True)
        return None
    
    def _extract_image_url(self, soup: BeautifulSoup) -> Optional[str]:
        """이미지 URL을 추출합니다."""
        if self.config.image_selectors is None:
            return None
        for selector in self.config.image_selectors:
            if selector.startswith("meta"):
                meta = soup.select_one(selector)
                if meta:
                    content = meta.get("content")
                    if content and isinstance(content, str):
                        return content
            else:
                img = soup.select_one(selector)
                if img:
                    src = img.get("src")
                    if src and isinstance(src, str):
                        return src
        return None

class ChosunCrawler(BaseNewsCrawler):
    """조선일보 크롤러 클래스"""
    
    CATEGORY_URLS = {
        Category.ECONOMY: "https://www.chosun.com/economy/",
        Category.POLITICS: "https://www.chosun.com/politics/",
        Category.NATIONAL: "https://www.chosun.com/national/",
        Category.CULTURE: "https://www.chosun.com/culture-style/",
        Category.INTERNATIONAL: "https://www.chosun.com/international/",
        Category.SPORTS: "https://www.chosun.com/sports/"
    }
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.collected_titles: Set[str] = set()
        self.ui = ConsoleUI()
        self.article_service = ArticleService()
    
    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        """특정 카테고리의 기사를 크롤링합니다."""
        articles = []
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            self.ui.print_category_start(category.value)
            base_url = self.CATEGORY_URLS[category]
            
            await page.goto(base_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1000)
            
            # 더보기 버튼을 클릭하여 충분한 기사 수집
            await self._load_more_articles(page, category)
            
            # 기사 링크 추출 및 크롤링
            links_and_titles = await self._extract_article_links(page, category)
            
            # 기사 내용 추출
            articles = await self._extract_articles(page, category, links_and_titles)
            
            self.ui.print_category_complete(category.value, len(articles))
            
        except Exception as e:
            logger.error(f"{category.value} 크롤링 실패: {str(e)}")
        finally:
            await page.close()
            await context.close()
        
        return articles
    
    async def _load_more_articles(self, page: Page, category: Category) -> None:
        """더보기 버튼을 클릭하여 중복 없는 기사 30개가 모일 때까지 반복합니다."""
        collected_urls = set()
        prev_count = 0
        for click_count in range(self.config.max_more_clicks):
            # 현재 기사 링크 추출 (중복 없는 set)
            current_links = await self._get_current_article_links(page)
            for url, _ in current_links:
                normalized_url = url.split('?')[0] if '?' in url else url
                collected_urls.add(normalized_url)
            
            # 목표 기사 수에 도달하면 중단
            if len(collected_urls) >= self.config.articles_per_category:
                break
            
            # 더보기 버튼 클릭
            more_btn = await page.query_selector("#load-more-stories")
            if more_btn:
                await more_btn.click()
                await page.wait_for_timeout(self.config.wait_timeout * 2)
                await page.wait_for_load_state("networkidle", timeout=10000)
            else:
                break
            
            # 더보기를 눌러도 새로운 기사가 하나도 추가되지 않으면 중단
            if len(collected_urls) == prev_count:
                break
            prev_count = len(collected_urls)
    
    async def _get_current_article_links(self, page: Page) -> List[Tuple[str, str]]:
        """현재 페이지의 기사 링크와 제목을 추출합니다."""
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        links_and_titles = []
        for a in soup.select(self.config.headline_selector):
            href = a.get('href')
            title = a.get_text(strip=True)
            
            if isinstance(href, list):
                href = href[0] if href else None
                
            if href and title and re.search(r'/20[0-9]{2}/[01][0-9]/[0-3][0-9]/', href):
                if href.startswith('/'):
                    full_url = f"https://www.chosun.com{href}"
                else:
                    full_url = href
                links_and_titles.append((full_url, title))
        
        return links_and_titles
    
    async def _extract_article_links(self, page: Page, category: Category) -> List[Tuple[str, str]]:
        """최종 기사 링크와 제목을 추출합니다."""
        links_and_titles = await self._get_current_article_links(page)
        
        # 중복 제거 (URL 기준)
        unique_links = []
        seen_urls = set()
        
        for url, title in links_and_titles:
            # URL 정규화 (쿼리 파라미터 제거)
            normalized_url = url.split('?')[0] if '?' in url else url
            
            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                unique_links.append((url, title))
        
        return unique_links
    
    async def _extract_articles(self, page: Page, category: Category, links_and_titles: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        """기사 내용을 추출합니다."""
        articles = []
        processed_count = 0
        skipped_duplicates = 0
        
        for i, (url, title) in enumerate(links_and_titles):
            if processed_count >= self.config.articles_per_category:
                break
            
            # 중복 제목 체크
            if title in self.collected_titles:
                skipped_duplicates += 1
                continue
            
            try:
                article = await self.extractor.extract_article_content(page, url)
                if article:
                    # 추출된 제목으로 다시 중복 체크
                    extracted_title = article['title']
                    if extracted_title in self.collected_titles:
                        skipped_duplicates += 1
                        continue
                    
                    article["category"] = category.value
                    article["source"] = "chosun"
                    articles.append(article)
                    self.collected_titles.add(extracted_title)
                    processed_count += 1
                    
                    # 진행 상황 출력
                    self.ui.print_progress(category.value, processed_count, self.config.articles_per_category, len(articles))
                    
                else:
                    logger.debug(f"{category.value}: 기사 추출 실패 - {url}")
                    
            except Exception as e:
                logger.error(f"{category.value} 기사 추출 실패: {url} - {e}")
        
        return articles
    
    async def crawl_all_categories(self, test_mode: bool = False) -> List[Dict[str, Any]]:
        """모든 카테고리를 크롤링합니다. test_mode=True면 국제/스포츠는 제외합니다."""
        all_articles = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, 
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            try:
                for category in Category:
                    if test_mode and category in [Category.INTERNATIONAL, Category.SPORTS]:
                        continue
                    articles = await self.crawl_category(browser, category)
                    all_articles.extend(articles)
                    
            finally:
                await browser.close()
        
        return all_articles
    
    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        """기사를 파일로 저장합니다."""
        today = datetime.now().strftime("%Y%m%d")
        filename = f"chosun_{today}.jsonl"
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        filepath = raw_dir / filename
        
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False) + '\n')
        
        return str(filepath)
    
    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        """기사를 Supabase 데이터베이스에 저장합니다."""
        try:
            # Article 모델로 변환
            article_models = []
            for article_dict in articles:
                # published_at 파싱
                published_at = None
                if article_dict.get('published_at'):
                    try:
                        if isinstance(article_dict['published_at'], str):
                            published_at = datetime.fromisoformat(article_dict['published_at'].replace('Z', '+00:00'))
                        else:
                            published_at = article_dict['published_at']
                    except:
                        published_at = None
                
                article_model = Article(
                    title=article_dict['title'],
                    url=article_dict['url'],
                    category=article_dict['category'],
                    content_full=article_dict.get('content_full'),
                    published_at=published_at,
                    author=article_dict.get('author'),
                    image_url=article_dict.get('image_url'),
                    bias="center"  # 기본값
                )
                article_models.append(article_model)
            
            # 데이터베이스에 저장
            saved_count = await self.article_service.save_articles(article_models)
            return saved_count
            
        except Exception as e:
            logger.error(f"데이터베이스 저장 실패: {e}")
            raise

async def main():
    """메인 함수"""
    try:
        # 환경변수 체크
        import os
        if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_ANON_KEY"):
            print("⚠️  경고: Supabase 환경변수가 설정되지 않았습니다.")
            print("   apps/backend/.env 파일에 SUPABASE_URL과 SUPABASE_ANON_KEY를 설정하세요.")
            print("   데이터베이스 저장을 건너뛰고 파일 저장만 진행합니다.")
        
        config = CrawlerConfig()
        crawler = ChosunCrawler(config)
        
        # UI 헤더 출력
        crawler.ui.print_header()
        
        # 모든 카테고리 크롤링 (6개 카테고리)
        articles = await crawler.crawl_all_categories(test_mode=False)
        
        if articles:
            # 파일 저장
            filepath = await crawler.save_articles(articles)
            
            # 데이터베이스 저장 (환경변수가 설정된 경우에만)
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
            
            # 최종 요약 출력
            crawler.ui.print_summary(len(articles), filepath)
        else:
            print("❌ 크롤링된 기사가 없습니다.")
        
    except Exception as e:
        logger.error(f"크롤링 실패: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 