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

# Supabase 연동 import
sys.path.append(str(Path(__file__).parent.parent))
from app.services.article_service import ArticleService
from app.models.article import Article
from crawler.base_crawler import BaseNewsCrawler
from crawler.utils import dict_to_article

# rich 스타일 터미널 피드백용 ConsoleUI
class ConsoleUI:
    @staticmethod
    def print_header():
        print("\n" + "="*60)
        print("🚀 동아일보 크롤러 시작")
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

class Category(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class CrawlerConfig:
    max_pages: int = 10
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10

class DongaArticleExtractor:
    def __init__(self, config: CrawlerConfig):
        self.config = config

    def parse_article_list(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        ul = soup.find("ul", class_="row_list")
        if not ul or not isinstance(ul, Tag):
            return articles
        for li in ul.find_all("li"):
            if not isinstance(li, Tag):
                continue
            art = {}
            article_tag = li.find("article", class_="news_card")
            if not article_tag or not isinstance(article_tag, Tag):
                continue
            # URL, 이미지
            news_head = article_tag.find("header", class_="news_head")
            a_tag = news_head.find("a") if news_head and isinstance(news_head, Tag) else None
            if a_tag and isinstance(a_tag, Tag) and a_tag.has_attr("href"):
                art["url"] = a_tag["href"]
            img_tag = a_tag.find("img") if a_tag and isinstance(a_tag, Tag) else None
            if img_tag and isinstance(img_tag, Tag) and img_tag.has_attr("src"):
                art["image_url"] = img_tag["src"]
            # 제목
            h4_tag = article_tag.find("h4", class_="tit")
            if h4_tag and isinstance(h4_tag, Tag):
                title_a = h4_tag.find("a")
                art["title"] = title_a.get_text(strip=True) if title_a and isinstance(title_a, Tag) else None
            # 요약
            desc_tag = article_tag.find("p", class_="desc")
            art["summary_excerpt"] = desc_tag.get_text(strip=True) if desc_tag and isinstance(desc_tag, Tag) else None
            # 발행일
            date_tag = article_tag.find("span", class_="date")
            art["published_at"] = date_tag.get_text(strip=True) if date_tag and isinstance(date_tag, Tag) else None
            articles.append(art)
        return articles

    def parse_article_detail(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        # 본문
        content = None
        news_view = soup.find("section", class_="news_view")
        if news_view and isinstance(news_view, Tag):
            for tag in list(news_view.find_all(["figure", "script", "style", "div"], recursive=True)):
                if not isinstance(tag, Tag):
                    continue
                if tag.name == "div":
                    tag_classes = tag.get("class")
                    if tag_classes and any(isinstance(cls, str) and (cls.startswith("view_") or "ad" in cls) for cls in tag_classes):
                        tag.decompose()
                else:
                    tag.decompose()
            content = news_view.get_text("\n", strip=True)
        # 발행일
        published_at = None
        news_info = soup.find("ul", class_="news_info")
        if news_info and isinstance(news_info, Tag):
            date_spans = [span for span in news_info.find_all("span", {"aria-hidden": "true"}) if isinstance(span, Tag)]
            if date_spans:
                published_at = date_spans[0].get_text(strip=True)
        # 기자명
        author = None
        byline = soup.find("div", class_="byline")
        if byline and isinstance(byline, Tag):
            text = byline.get_text(strip=True)
            if "기자" in text:
                author = text.split("기자")[0].strip()
            elif "@" in text:
                author = text.split("@")[0].strip()
            else:
                author = text
        return {
            "content_full": content or None,
            "published_at": published_at or None,
            "author": author or None
        }

class DongaCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: "https://www.donga.com/news/Economy"
    }
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.extractor = DongaArticleExtractor(config)
        self.ui = ConsoleUI()
        self.article_service = ArticleService()
        self.media_id = None
        self.bias = None

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        self.ui.print_category_start(category.value)
        url = self.CATEGORY_URLS[category]
        page = await browser.new_page()
        article_candidates: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()
        current_page = 1
        while len(article_candidates) < self.config.articles_per_category and current_page <= self.config.max_pages:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1000)
            html = await page.content()
            page_articles = self.extractor.parse_article_list(html)
            for art in page_articles:
                if art.get("url") and art["url"] not in seen_urls and len(article_candidates) < self.config.articles_per_category:
                    article_candidates.append(art)
                    seen_urls.add(art["url"])
            # 다음 페이지 URL 생성
            if current_page == 1:
                url = "https://www.donga.com/news/Economy?p=11&prod=news&ymd=&m="
            else:
                next_p = 1 + current_page * 10
                url = f"https://www.donga.com/news/Economy?p={next_p}&prod=news&ymd=&m="
            current_page += 1
        await page.close()
        # 상세 기사 파싱
        detailed_articles = []
        detail_page = await browser.new_page()
        try:
            for idx, art in enumerate(article_candidates):
                await detail_page.goto(art["url"], wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await detail_page.wait_for_timeout(500)
                detail_html = await detail_page.content()
                detail = self.extractor.parse_article_detail(detail_html)
                # 필드 병합 및 누락 필드 None 처리
                merged = {**art, **detail}
                merged["category"] = category.value
                # 날짜 변환
                published_at = merged.get("published_at")
                if published_at:
                    try:
                        from dateutil.parser import parse as dtparse
                        merged["published_at"] = dtparse(published_at)
                    except Exception:
                        merged["published_at"] = None
                else:
                    merged["published_at"] = None
                detailed_articles.append(merged)
                self.ui.print_progress(category.value, len(detailed_articles), self.config.articles_per_category, len(detailed_articles))
                if len(detailed_articles) >= self.config.articles_per_category:
                    break
        finally:
            await detail_page.close()
        self.ui.print_category_complete(category.value, len(detailed_articles))
        return detailed_articles

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
        dongailbo_media_id = "a076175c-b74e-4740-aa7d-04227fbdd44f"
        if self.media_id is None or self.bias is None:
            media = await self.article_service.get_or_create_media("동아일보")
            if media:
                self.media_id = dongailbo_media_id
                self.bias = media["bias"]
            else:
                logging.error("동아일보 media_outlets 정보 조회 실패!")
                return ""
        article_models = []
        for art in articles:
            art["media_id"] = dongailbo_media_id
            art["bias"] = self.bias or "center"
            published_at = art.get("published_at")
            if published_at and isinstance(published_at, str):
                try:
                    from dateutil.parser import parse as dtparse
                    published_at = dtparse(published_at)
                except Exception:
                    published_at = None
            art["published_at"] = published_at
            # media_id가 누락되지 않도록 dict_to_article 호출 시 명시적으로 전달
            article_models.append(dict_to_article(art))
        today = datetime.now().strftime("%Y%m%d")
        out_dir = Path("crawler/data/raw")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"donga_articles_{today}.jsonl"
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            for art in articles:
                await f.write(json.dumps(art, ensure_ascii=False, default=str) + "\n")
        saved_count = await self.article_service.save_articles(article_models)
        logging.info(f"✅ {saved_count}개 기사 DB 저장 완료")
        self.ui.print_summary(len(articles), str(out_path))
        return str(out_path)

async def main():
    config = CrawlerConfig()
    crawler = DongaCrawler(config)
    crawler.ui.print_header()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        articles = await crawler.crawl_all_categories()
        await browser.close()
    if articles:
        await crawler.save_articles(articles)

if __name__ == "__main__":
    asyncio.run(main()) 