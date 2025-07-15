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
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Browser, Page

# Supabase 연동 import (조선일보와 동일)
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

# 로깅 설정 (조선일보와 동일)
def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "crawler_joongang.log", encoding="utf-8")
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
    POLITICS = "정치"
    ECONOMY = "경제"
    SOCIETY = "사회"
    INTERNATIONAL = "국제"
    SPORTS = "스포츠"
    CULTURE = "문화"

@dataclass
class CrawlerConfig:
    max_pages: int = 10
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10

class ConsoleUI:
    @staticmethod
    def print_header():
        print("\n" + "="*60)
        print("🚀 중앙일보 크롤러 시작")
        print("="*60)
    @staticmethod
    def print_category_start(category: str):
        print(f"\n📰 {category} 카테고리 크롤링 중...")
    @staticmethod
    def print_progress(category: str, current: int, target: int, total_articles: int):
        progress = min(100, int(current / target * 100))
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        print(f"   {bar} {current}/{target} ({progress}%) - 총 {total_articles}개 기사")
    @staticmethod
    def print_category_complete(category: str, count: int):
        print(f"✅ {category}: {count}개 기사 수집 완료")
    @staticmethod
    def print_summary(total_articles: int, filepath: str):
        print("\n" + "="*60)
        print(f"🎉 크롤링 완료!")
        print(f"📊 총 {total_articles}개 기사 수집")
        print(f"💾 저장 위치: {filepath}")
        print("="*60 + "\n")

class JoongangCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.POLITICS: "https://www.joongang.co.kr/politics",
        Category.ECONOMY: "https://www.joongang.co.kr/money",
        Category.SOCIETY: "https://www.joongang.co.kr/society",
        Category.INTERNATIONAL: "https://www.joongang.co.kr/world",
        Category.SPORTS: "https://www.joongang.co.kr/sports",
        Category.CULTURE: "https://www.joongang.co.kr/culture",
    }
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.ui = ConsoleUI()
        self.article_service = ArticleService()
        self.media_id = None  # 중앙일보 media_id (DB에서 조회 필요)
        self.bias = 'right'   # 중앙일보 bias (DB에서 조회 필요)

    async def _extract_article_detail_from_page(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """
        기사 상세 페이지에서 본문, 기자, 이미지, 날짜를 추출합니다.
        """
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(500)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            # 제목
            title_tag = soup.find("h1")
            title = title_tag.get_text(strip=True) if title_tag else None
            # 본문 (여러 셀렉터 후보 순차 시도)
            content_tag = (
                soup.find("div", id="article_body") or
                soup.find("div", class_="article_body") or
                soup.find("div", class_="article_content") or
                soup.find("div", id="articleContent")
            )
            content = content_tag.get_text("\n", strip=True) if content_tag else None
            # 기자
            author_tag = soup.find("span", class_="byline_name") or soup.find("span", class_="name")
            author = author_tag.get_text(strip=True) if author_tag else None
            # 대표 이미지
            image_tag = soup.find("meta", property="og:image")
            image_url = image_tag.get("content") if isinstance(image_tag, Tag) and image_tag.has_attr("content") else None
            # 날짜
            date_tag = soup.find("meta", property="article:published_time")
            published_at = date_tag.get("content") if isinstance(date_tag, Tag) and date_tag.has_attr("content") else None
            return {
                "title": title,
                "content_full": content,
                "author": author,
                "image_url": image_url,
                "published_at": published_at
            }
        except Exception as e:
            logger.debug(f"상세 기사 추출 실패: {url} - {str(e)}")
            return None

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
            page_articles = await self._extract_article_list_from_page(page)
            for art in page_articles:
                if art["url"] not in seen_urls and len(article_candidates) < self.config.articles_per_category:
                    article_candidates.append(art)
                    seen_urls.add(art["url"])
            next_url = await self._get_next_page_url(page, current_page + 1, category)
            if not next_url:
                break
            await page.goto(next_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            current_page += 1
        await page.close()
        # 2. 상세 기사 추출(순차적으로, 진행바 표시)
        detailed_articles = []
        detail_page = await browser.new_page()
        try:
            for idx, art in enumerate(article_candidates):
                detail = await self._extract_article_detail_from_page(detail_page, art["url"])
                if detail and detail.get("content_full"):
                    art.update(detail)
                    detailed_articles.append(art)
                self.ui.print_progress(category.value, len(detailed_articles), self.config.articles_per_category, len(detailed_articles))
                if len(detailed_articles) >= self.config.articles_per_category:
                    break
        finally:
            await detail_page.close()
        self.ui.print_category_complete(category.value, len(detailed_articles))
        return detailed_articles

    async def _get_next_page_url(self, page: Page, next_page_num: int, category: Category) -> Optional[str]:
        """
        현재 페이지에서 다음 페이지 url을 추출합니다.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        nav = soup.find("nav", class_="pagination_type02")
        if not isinstance(nav, Tag):
            return None
        # 페이지 번호에 해당하는 a 태그 찾기
        for a in nav.find_all("a", class_="page_link"):
            if a.get("aria-label", "").startswith(str(next_page_num)) or a.get_text(strip=True) == str(next_page_num):
                href = a.get("href")
                if href and href.startswith("http"):
                    return href
        return None

    async def crawl_all_categories(self) -> List[Dict[str, Any]]:
        all_articles: List[Dict[str, Any]] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for category in self.CATEGORY_URLS.keys():
                articles = await self.crawl_category(browser, category)
                for art in articles:
                    art["category"] = category.value
                all_articles.extend(articles)
            await browser.close()
        self.ui.print_summary(len(all_articles), "(저장 전)")
        return all_articles

    async def save_articles(self, articles: List[Dict[str, Any]]) -> str:
        # 1. 중앙일보 media_id, bias 조회 (최초 1회만)
        if self.media_id is None:
            media = await self.article_service.get_or_create_media("중앙일보")
            if media:
                self.media_id = media["id"]
            else:
                logger.error("중앙일보 media_outlets 정보 조회 실패!")
                return ""
        # 2. 기사에 media_id, bias 추가 및 Article 변환
        article_models = []
        for art in articles:
            art["media_id"] = self.media_id
            art["bias"] = self.bias
            # published_at 변환
            published_at = art.get("published_at")
            if published_at and isinstance(published_at, str):
                try:
                    from dateutil.parser import parse as dtparse
                    published_at = dtparse(published_at)
                except Exception:
                    published_at = None
            article_models.append(Article(
                title=art["title"],
                url=art["url"],
                category=art.get("category", ""),
                content_full=art.get("content_full"),
                published_at=published_at,
                author=art.get("author"),
                image_url=art.get("image_url"),
                bias=art.get("bias", "right"),
                media_id=art.get("media_id")
            ))
        # 3. 파일 저장
        today = datetime.now().strftime("%Y%m%d")
        out_dir = Path("crawler/data/raw")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"joongang_{today}.jsonl"
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            for art in articles:
                await f.write(json.dumps(art, ensure_ascii=False) + "\n")
        # 4. Supabase 저장
        saved_count = await self.article_service.save_articles(article_models)
        logger.info(f"✅ {saved_count}개 기사 DB 저장 완료")
        # 5. 요약 출력
        self.ui.print_summary(len(articles), str(out_path))
        return str(out_path)

    async def _extract_article_list_from_page(self, page: Page) -> List[Dict[str, Any]]:
        """
        현재 페이지에서 기사 리스트(링크, 제목, 요약, 이미지, 날짜)를 추출합니다.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        ul = soup.find("ul", {"id": "story_list", "class": "story_list"})
        if not isinstance(ul, Tag):
            return articles
        for li in ul.find_all("li", class_="card"):
            # 링크 및 제목
            a_tag = li.find("h2", class_="headline").find("a") if li.find("h2", class_="headline") else None
            url = a_tag["href"] if a_tag and a_tag.has_attr("href") else None
            title = a_tag.get_text(strip=True) if a_tag else None
            # 요약
            desc = li.find("p", class_="description")
            summary = desc.get_text(strip=True) if desc else None
            # 이미지
            img_tag = li.find("figure", class_="card_image").find("img") if li.find("figure", class_="card_image") else None
            image_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else None
            # 날짜
            date_tag = li.find("div", class_="meta").find("p", class_="date") if li.find("div", class_="meta") else None
            published_at = date_tag.get_text(strip=True) if date_tag else None
            if url and title:
                articles.append({
                    "url": url,
                    "title": title,
                    "summary_excerpt": summary,
                    "image_url": image_url,
                    "published_at": published_at
                })
        return articles

async def main():
    config = CrawlerConfig()
    crawler = JoongangCrawler(config)
    crawler.ui.print_header()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        articles = await crawler.crawl_all_categories()
        await browser.close()
    if articles:
        await crawler.save_articles(articles)

if __name__ == "__main__":
    asyncio.run(main()) 