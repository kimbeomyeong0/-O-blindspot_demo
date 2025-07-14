import asyncio
import json
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple
from dataclasses import dataclass
from enum import Enum
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.theme import Theme
import sys
import logging
import os
import aiofiles
import re
from datetime import datetime

# Supabase 연동 및 서비스/모델 import
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

console = Console(theme=Theme({
    "success": "bold green",
    "fail": "bold red",
    "info": "bold cyan"
}))

def print_status(msg, status="info"):
    console.print(msg, style=status)

class YonhapCategory(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class YonhapCrawlerConfig:
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10
    max_pages: int = 10
    # 주요 셀렉터 (실제 HTML 구조 반영)
    list_selector: str = 'section.box-type011.box-major01 ul.list01 > li'
    link_selector: str = 'a.tit-news'
    title_selector: str = 'span.title01'
    date_selector: str = 'span.txt-time'
    # 상세 페이지용
    article_selector: str = '#articleWrap > div.story-news.article'
    detail_title_selector: str = '#container > div.container591 > div.content90 > header > h1'
    detail_date_selector: str = '#newsUpdateTime01 > p.txt-time01'
    detail_author_selector: str = '#swiper-wrapper-225973efd93983a3 > div > div > strong'
    detail_image_selector: str = '#articleWrap > div.story-news.article img'

class YonhapCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        YonhapCategory.ECONOMY: "https://www.yna.co.kr/economy/index?site=navi_economy_depth01"
    }

    def __init__(self, config: YonhapCrawlerConfig):
        self.config = config
        self.article_service = ArticleService()

    async def fetch_article_list(self, page: Page, category: YonhapCategory, min_count: int = 30, max_pages: int = 10) -> List[Tuple[str, str, Optional[datetime]]]:
        """카테고리별 기사 리스트 URL, 제목, 발행일 추출 (중복/파싱 실패 고려, min_count만큼 확보될 때까지 여러 페이지 반복)"""
        article_links = []
        seen_urls = set()
        page_num = 1
        while len(article_links) < min_count and page_num <= max_pages:
            if page_num == 1:
                url = self.CATEGORY_URLS[category]
            else:
                url = f"https://www.yna.co.kr/economy/all/{page_num}"
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(500)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for li in soup.select('ul.list01 > li'):
                a = li.select_one('a.tit-news')
                title_el = li.select_one('span.title01')
                time_el = li.select_one('span.txt-time')
                if a and a.has_attr('href') and title_el and time_el:
                    href = a['href']
                    if isinstance(href, list):
                        href = href[0] if href else ''
                    if not isinstance(href, str):
                        continue
                    if not href.startswith('http'):
                        href = f"https://www.yna.co.kr{href}"
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = title_el.get_text(strip=True)
                    published_at_str = time_el.get_text(strip=True)
                    now = datetime.now()
                    published_at = None
                    try:
                        published_at = datetime.strptime(f"{now.year}-{published_at_str}", "%Y-%m-%d %H:%M")
                    except Exception:
                        published_at = None
                    article_links.append((href, title, published_at))
                if len(article_links) >= min_count:
                    break
            page_num += 1
        return article_links[:min_count]

    async def parse_article(self, page: Page, url: str, published_at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """기사 상세 정보 파싱 (본문, 제목, 발행일, 기자명, 이미지 등)"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_timeout(1000)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            # 제목
            title_el = soup.select_one(self.config.detail_title_selector)
            title = title_el.get_text(strip=True) if title_el else None
            if not title or len(title) < self.config.min_title_length:
                return None

            # 본문: .story-news.article 내 모든 <p> 텍스트 합치기
            article_area = soup.select_one('.story-news.article')
            content = None
            if article_area:
                for aside in article_area.find_all('aside'):
                    aside.decompose()
                for ad in article_area.find_all(class_=['ads-article01', 'ads-box', 'aside-box004', 'aside-box211', 'aside-box300', 'aside-box301']):
                    ad.decompose()
                ps = article_area.find_all('p')
                content = '\n'.join([p.get_text(strip=True) for p in ps if p.get_text(strip=True)])
            if not content or len(content) < self.config.min_content_length:
                article_area = soup.select_one(self.config.article_selector)
                if article_area:
                    content = article_area.get_text(strip=True)
            if not content or len(content) < self.config.min_content_length:
                return None

            # 발행일: 목록에서 받은 published_at이 있으면 우선 사용, 없으면 상세에서 추출
            if not published_at:
                date_el = soup.select_one('span.txt-time')
                published_at_str = date_el.get_text(strip=True) if date_el else None
                now = datetime.now()
                try:
                    published_at = datetime.strptime(f"{now.year}-{published_at_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    published_at = None

            # 기자명: .writer-zone01 .tit-name a
            author_el = soup.select_one('.writer-zone01 .tit-name a')
            author = author_el.get_text(strip=True) if author_el else None
            if not author:
                author_el = soup.select_one(self.config.detail_author_selector)
                author = author_el.get_text(strip=True) if author_el else None

            # 대표 이미지: .comp-box img 또는 .story-news.article img
            image_el = soup.select_one('.comp-box img')
            if not image_el:
                image_el = soup.select_one('.story-news.article img')
            image_url = image_el['src'] if image_el and image_el.has_attr('src') else None
            if isinstance(image_url, list):
                image_url = image_url[0] if image_url else ''
            if image_url and isinstance(image_url, str) and image_url.startswith('//'):
                image_url = 'https:' + image_url
            if not image_url:
                image_el = soup.select_one(self.config.detail_image_selector)
                image_url = image_el['src'] if image_el and image_el.has_attr('src') else None

            return {
                "title": title,
                "url": url,
                "content_full": content,
                "published_at": published_at,
                "author": author,
                "image_url": image_url
            }
        except Exception as e:
            return None

    async def save_to_supabase(self, articles: List[Dict[str, Any]], media_id: str, bias: str) -> int:
        """Supabase articles 테이블에 기사 저장 (중복 URL unique constraint 자동 방지)"""
        try:
            article_models = []
            for article_dict in articles:
                # published_at이 datetime이 아니면 None 처리
                published_at = article_dict.get('published_at')
                if isinstance(published_at, str):
                    published_at = None
                article_model = Article(
                    title=article_dict['title'],
                    url=article_dict['url'],
                    category='경제',
                    content_full=article_dict.get('content_full'),
                    published_at=published_at,
                    author=article_dict.get('author'),
                    image_url=article_dict.get('image_url'),
                    bias=bias,
                    media_id=media_id,
                )
                article_models.append(article_model)
            saved_count = await self.article_service.save_articles(article_models)
            return saved_count
        except Exception as e:
            return 0

    async def crawl_category(self, browser: Browser, category: YonhapCategory) -> List[Dict[str, Any]]:
        """카테고리별 기사 크롤링(중복 방지, 30개 미만이면 추가 페이지 탐색)"""
        articles = []
        article_links: Set[Tuple[str, str]] = set()
        min_count = self.config.articles_per_category
        max_pages = self.config.max_pages
        success_count = 0
        fail_count = 0
        console.rule(f"[bold blue]📰 {category.value} 카테고리 기사 리스트 수집 시작")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            links = await self.fetch_article_list(page, category, min_count=min_count, max_pages=max_pages)
            article_links = set(links)
            console.print(f"[bold green]✅ 기사 리스트 수집 완료: {len(article_links)}개[/bold green]")
            # 기사 상세 파싱
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"기사 상세 추출 중...", total=len(article_links))
                for idx, (url, title, published_at) in enumerate(article_links):
                    progress.update(task, advance=1, description=f"({idx+1}/{len(article_links)})")
                    try:
                        article = await self.parse_article(page, url, published_at=published_at)
                        if article:
                            articles.append(article)
                            success_count += 1
                            print_status(f"[상세 {idx+1}/{len(article_links)}] '{title[:30]}' 성공 (누적 성공: {success_count}, 실패: {fail_count})", "success")
                        else:
                            fail_count += 1
                            print_status(f"[상세 {idx+1}/{len(article_links)}] '{title[:30]}' 본문 없음 (누적 성공: {success_count}, 실패: {fail_count})", "fail")
                    except Exception as e:
                        fail_count += 1
                        print_status(f"[상세 {idx+1}/{len(article_links)}] '{title[:30]}' 오류: {e} (누적 성공: {success_count}, 실패: {fail_count})", "fail")
                        continue
                await page.close()
                await context.close()
        console.rule(f"[bold magenta]📝 {category.value} 카테고리 파싱 요약: 성공 {success_count} / 실패 {fail_count}")
        return articles[:min_count]

    async def crawl_all_categories(self) -> List[Dict[str, Any]]:
        console.rule("[bold blue]🚀 연합뉴스 경제 크롤러 전체 파이프라인 시작")
        all_articles = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for category in YonhapCategory:
                articles = await self.crawl_category(browser, category)
                all_articles.extend(articles)
        console.rule(f"[bold magenta]🎉 전체 카테고리 크롤링 완료! 총 {len(all_articles)}개 기사")
        return all_articles

    async def save_articles(self, articles: List[dict]) -> str:
        if not articles:
            console.print("[bold red]저장할 기사가 없습니다.[/bold red]")
            return ""
        data_dir = Path("data/raw")
        data_dir.mkdir(parents=True, exist_ok=True)
        timestamp = asyncio.get_event_loop().time()
        filename = f"yonhap_articles_{int(timestamp)}.jsonl"
        filepath = data_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                await f.write(json.dumps(article, ensure_ascii=False, default=str) + '\n')
        return str(filepath)

    async def save_articles_to_db(self, articles: List[Dict[str, Any]], media_id: str, bias: str) -> int:
        return await self.save_to_supabase(articles, media_id, bias)

# --- 공통 유틸: 언론사명으로 media_id, bias 안전하게 가져오기 ---
async def get_media_info(media_name: str) -> Tuple[str, str]:
    svc = ArticleService()
    info = await svc.get_or_create_media(media_name)
    if info:
        return info["id"], info["bias"]
    return "", "center"

async def main():
    config = YonhapCrawlerConfig()
    crawler = YonhapCrawler(config)
    media_id, bias = await get_media_info('연합뉴스')
    articles = await crawler.crawl_all_categories()
    if articles:
        for article in articles:
            article["media_id"] = media_id
            article["bias"] = bias
        filepath = await crawler.save_articles(articles)
        await crawler.save_articles_to_db(articles, media_id, bias)
        console.rule("[bold magenta]🎉 크롤링 완료!")
        console.print(f"[bold yellow]📊 총 {len(articles)}개 기사 수집")
        console.print(f"[bold yellow]💾 저장 위치: {filepath}")
    else:
        console.print("[bold red]크롤링된 기사가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main()) 