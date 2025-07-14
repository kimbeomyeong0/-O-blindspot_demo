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
    POLITICS = "정치"
    ECONOMY = "경제"
    NATIONAL = "사회"
    INTERNATIONAL = "국제"
    SPORTS = "스포츠"
    CULTURE = "문화"
    ENTERTAINMENT = "연예"

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
    headline_selector: str = 'a[href*="/article/"]'
    title_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None
    date_selectors: Optional[List[str]] = None
    author_selectors: Optional[List[str]] = None
    image_selectors: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.title_selectors is None:
            self.title_selectors = ['h1', '.article-title', '.title', '[class*="title"]', 'h2']
        if self.content_selectors is None:
            self.content_selectors = [
                '.article-content', '.content', '[class*="content"]', 
                '.article-body', '.body', 'article', '.article-text'
            ]
        if self.date_selectors is None:
            self.date_selectors = [
                ".date", ".time", "[class*='date']", "[class*='time']", 
                ".published", ".article-date"
            ]
        if self.author_selectors is None:
            self.author_selectors = [
                ".author", ".byline", ".writer", ".reporter", "[class*='author']"
            ]
        if self.image_selectors is None:
            self.image_selectors = [
                ".article-image img", ".content img", "article img", ".thumb-img"
            ]

class ConsoleUI:
    """터미널 UI 관리 클래스"""
    
    @staticmethod
    def print_header():
        """크롤링 시작 헤더를 출력합니다."""
        print("\n" + "="*60)
        print("🚀 JTBC 뉴스 크롤러 시작")
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
                # 불필요한 요소 제거
                for unwanted in el.find_all(['script', 'style', 'nav', 'header', 'footer']):
                    unwanted.decompose()
                
                content = el.get_text(strip=True)
                if len(content) >= self.config.min_content_length:
                    return content
        return ""
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        """발행일을 추출합니다."""
        if self.config.date_selectors is None:
            return None
        
        for selector in self.config.date_selectors:
            el = soup.select_one(selector)
            if el:
                date_text = el.get_text(strip=True)
                # 날짜 패턴 찾기
                date_match = re.search(r'(\d{4})[.-](\d{1,2})[.-](\d{1,2})', date_text)
                if date_match:
                    return f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """기자를 추출합니다."""
        if self.config.author_selectors is None:
            return None
        
        for selector in self.config.author_selectors:
            el = soup.select_one(selector)
            if el:
                author = el.get_text(strip=True)
                if author and len(author) > 0:
                    return author
        return None
    
    def _extract_image_url(self, soup: BeautifulSoup) -> Optional[str]:
        """이미지 URL을 추출합니다."""
        if self.config.image_selectors is None:
            return None
        
        for selector in self.config.image_selectors:
            el = soup.select_one(selector)
            if el and el.get('src'):
                image_url = el.get('src')
                if image_url and not image_url.startswith('data:'):
                    return image_url
        return None

class JTBCNewsCrawler(BaseNewsCrawler):
    """JTBC 뉴스 크롤러 클래스"""
    
    CATEGORY_URLS = {
        Category.POLITICS: "https://news.jtbc.co.kr/sections/10",
        Category.ECONOMY: "https://news.jtbc.co.kr/sections/20",
        Category.NATIONAL: "https://news.jtbc.co.kr/sections/30",
        Category.INTERNATIONAL: "https://news.jtbc.co.kr/sections/40",
        Category.SPORTS: "https://news.jtbc.co.kr/sections/70",
        Category.CULTURE: "https://news.jtbc.co.kr/sections/50",
        Category.ENTERTAINMENT: "https://news.jtbc.co.kr/sections/60"
    }
    
    def __init__(self, config: CrawlerConfig):
        super().__init__()
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
        self.media_id = None  # JTBC media_id (DB에서 조회 필요)
        self.bias = 'left'    # JTBC bias (DB에서 조회 필요)
        self.base_url = "https://news.jtbc.co.kr"
    
    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        """특정 카테고리의 기사들을 크롤링합니다."""
        ConsoleUI.print_category_start(category.value)
        
        page = await browser.new_page()
        articles = []
        
        try:
            # 카테고리 페이지로 이동
            category_url = self.CATEGORY_URLS[category]
            await page.goto(category_url, wait_until="networkidle")
            
            # 더보기 버튼 클릭으로 더 많은 기사 로드
            await self._load_more_articles(page, category)
            
            # 기사 링크 추출
            links_and_titles = await self._extract_article_links(page, category)
            
            if not links_and_titles:
                logger.warning(f"{category.value}: 수집된 기사 링크가 없습니다")
                return []
            
            # 기사 상세 내용 추출
            articles = await self._extract_articles(page, category, links_and_titles)
            
            ConsoleUI.print_category_complete(category.value, len(articles))
            return articles
            
        except Exception as e:
            logger.error(f"{category.value} 크롤링 실패: {e}")
            return []
        finally:
            await page.close()
    
    async def _load_more_articles(self, page: Page, category: Category) -> None:
        """더보기 버튼을 클릭하여 더 많은 기사를 로드합니다."""
        for i in range(self.config.max_more_clicks):
            try:
                # 더보기 버튼 찾기
                more_button = page.locator("button:has-text('더보기')")
                if await more_button.count() > 0:
                    await more_button.click()
                    await page.wait_for_timeout(self.config.wait_timeout)
                    logger.debug(f"더보기 버튼 클릭 {i+1}회")
                else:
                    break
            except Exception as e:
                logger.debug(f"더보기 버튼 클릭 실패: {e}")
                break
    
    async def _get_current_article_links(self, page: Page) -> List[Tuple[str, str]]:
        """현재 페이지의 기사 링크들을 가져옵니다."""
        links_and_titles = []
        seen_links = set()
        
        try:
            # 기사 링크 요소들 찾기
            link_elements = await page.locator(self.config.headline_selector).all()
            
            for element in link_elements:
                try:
                    href = await element.get_attribute("href")
                    if href:
                        # 전체 URL로 변환
                        full_url = self.base_url + href if href.startswith("/") else href
                        
                        # 중복 체크 및 기사 URL 패턴 확인
                        if (full_url not in seen_links and 
                            "/article/" in full_url and
                            "NB" in full_url):  # JTBC 기사 ID 패턴
                            
                            # 제목 추출 시도
                            title = await element.text_content()
                            title = title.strip() if title else ""
                            
                            links_and_titles.append((full_url, title))
                            seen_links.add(full_url)
                            
                except Exception as e:
                    logger.debug(f"링크 추출 실패: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"링크 수집 실패: {e}")
        
        return links_and_titles
    
    async def _extract_article_links(self, page: Page, category: Category) -> List[Tuple[str, str]]:
        """기사 링크들을 추출합니다."""
        links_and_titles = await self._get_current_article_links(page)
        
        # 중복 제거 및 제한
        unique_links = []
        seen_urls = set()
        
        for url, title in links_and_titles:
            if url not in seen_urls:
                unique_links.append((url, title))
                seen_urls.add(url)
                
                if len(unique_links) >= self.config.articles_per_category:
                    break
        
        logger.info(f"{category.value}: {len(unique_links)}개 기사 링크 수집")
        return unique_links
    
    async def _extract_articles(self, page: Page, category: Category, links_and_titles: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        """기사 상세 내용을 추출합니다."""
        articles = []
        
        for i, (url, title) in enumerate(links_and_titles, 1):
            ConsoleUI.print_progress(category.value, i, len(links_and_titles), len(articles))
            
            try:
                article_data = await self.extractor.extract_article_content(page, url)
                if article_data:
                    article_data["category"] = category.value
                    articles.append(article_data)
                
                # 요청 간격 조절
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.debug(f"기사 추출 실패 {url}: {e}")
                continue
        
        return articles
    
    async def crawl_all_categories(self, test_mode: bool = False) -> List[Dict[str, Any]]:
        """모든 카테고리를 크롤링합니다."""
        ConsoleUI.print_header()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            try:
                all_articles = []
                
                for category in Category:
                    if test_mode and len(all_articles) >= 5:  # 테스트 모드에서는 5개만
                        break
                    
                    articles = await self.crawl_category(browser, category)
                    all_articles.extend(articles)
                
                # 결과 저장
                if all_articles:
                    await self.save_articles_to_db(all_articles)
                
                return all_articles
                
            except Exception as e:
                logger.error(f"크롤링 중 오류 발생: {e}")
                return []
            finally:
                await browser.close()
    
    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        """기사들을 JSON 파일로 저장합니다."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jtbc_articles_{timestamp}.json"
        
        async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(articles, ensure_ascii=False, indent=2))
        
        return filename
    
    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        """기사들을 Supabase DB에 저장합니다."""
        try:
            # JTBC media_id 조회 (최초 1회만)
            if not hasattr(self, 'media_id'):
                media = await self.article_service.get_or_create_media("JTBC 뉴스")
                if media:
                    self.media_id = media["id"]
                else:
                    logger.error("JTBC 뉴스 media_outlets 정보 조회 실패!")
                    return 0
            
            # Dict를 Article 객체로 변환
            article_objects = []
            for article_dict in articles:
                # published_at을 datetime 객체로 변환
                published_at = None
                if article_dict["published_at"]:
                    try:
                        if isinstance(article_dict["published_at"], str):
                            published_at = datetime.fromisoformat(article_dict["published_at"])
                        else:
                            published_at = article_dict["published_at"]
                    except:
                        published_at = datetime.now()
                
                article = Article(
                    title=article_dict["title"],
                    url=article_dict["url"],
                    content_full=article_dict.get("content_full"),
                    published_at=article_dict.get("published_at"),
                    author=article_dict.get("author"),
                    image_url=article_dict.get("image_url"),
                    category=article_dict["category"],
                    media_id=self.media_id,
                    bias=self.bias
                )
                article_objects.append(article)
            
            saved_count = await self.article_service.save_articles(article_objects)
            logger.info(f"💾 {saved_count}개 기사 DB 저장 완료")
            return saved_count
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
            return 0

async def main():
    """메인 실행 함수"""
    config = CrawlerConfig()
    crawler = JTBCNewsCrawler(config)
    
    # 전체 카테고리 크롤링
    articles = await crawler.crawl_all_categories(test_mode=False)
    
    if articles:
        filename = await crawler.save_articles(articles)
        ConsoleUI.print_summary(len(articles), filename)
    else:
        print("❌ 수집된 기사가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main()) 