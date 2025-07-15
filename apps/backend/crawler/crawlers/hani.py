import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
import os
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console
from datetime import datetime

# Supabase 연동 및 서비스/모델 import
import sys
sys.path.append(str(Path(__file__).parent.parent))
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler

class HaniCategory(Enum):
    ECONOMY = "경제"
    # 추후 확장 가능

@dataclass
class HaniCrawlerConfig:
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 50
    min_title_length: int = 10
    # 주요 셀렉터
    list_selector: str = '#content > div.section_inner__Gn71W > div.section_flexInner__jGNGY.section_content__CNIbB > div.section_left__5BOCT'
    article_selector: str = '#renewal2023'
    title_selector: str = '#renewal2023 > h3'
    date_selector: str = '#renewal2023 > div.ArticleDetailView_articleDetail__IT2fh > ul'
    author_selector: str = '#content > div:nth-child(1) > div > div:nth-child(3) > div.ArticleDetail_reporterWrap__GHM9e > div > div > a > div.ArticleDetailReporter_nameInfo__SPYjX > div.ArticleDetailReporter_name__kXCEK'
    image_selector: str = '#content > div.section_inner__Gn71W > div.section_flexInner__jGNGY.section_content__CNIbB > div.section_left__5BOCT > div > ul > li:nth-child(3) > article > div > a > div > div > div > img'

class HaniCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        HaniCategory.ECONOMY: "https://www.hani.co.kr/arti/economy?page={page}"
    }

    def __init__(self, config: HaniCrawlerConfig):
        self.config = config
        self.article_service = ArticleService()
        # 기타 필요한 초기화

    async def fetch_article_list(self, browser: Browser, category: HaniCategory, min_count: int = 30, max_pages: int = 10) -> List[Dict[str, str]]:
        """카테고리별 기사 리스트 URL 및 카드 날짜 추출 (중복/파싱 실패 고려, min_count만큼 확보될 때까지 여러 페이지 반복)"""
        article_cards = []
        context = await browser.new_context()
        page = await context.new_page()
        console = Console()
        try:
            for page_num in range(1, max_pages + 1):
                url = self.CATEGORY_URLS[category].format(page=page_num)
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await page.wait_for_selector(self.config.list_selector, timeout=self.config.page_timeout)
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                list_area = soup.select_one(self.config.list_selector)
                if not list_area:
                    continue
                for li in list_area.find_all('li', class_="ArticleList_item___OGQO"):
                    a = li.find('a', href=True)
                    if not a:
                        continue
                    href = a['href']
                    if href.startswith('/arti/economy/'):
                        full_url = f"https://www.hani.co.kr{href}"
                        # robust 카드 날짜 추출
                        date_div = li.select_one('.BaseArticleCard_date__4R8Ru')
                        card_date = date_div.get_text(strip=True) if date_div else None
                        console.print(f"[magenta]카드 날짜 추출: {card_date} ({full_url})[/magenta]")
                        article_cards.append({"url": full_url, "card_published_at": card_date})
                if len(article_cards) >= min_count:
                    break
        finally:
            await page.close()
            await context.close()
        return article_cards[:min_count]

    def parse_date_string(self, dt):
        try:
            # 접두사 및 한글, 불필요한 문자 제거
            if dt:
                import re
                # '등록', '발행', '수정' 등 한글 접두사 및 불필요한 문자 제거
                dt = re.sub(r'^(등록|발행|수정)[ :\-]*', '', dt)
                dt = re.sub(r'[^0-9\-: ]', '', dt)  # 숫자, -, :, 공백만 남김
                dt = dt.strip()
            # 2025-07-15 07:00
            if dt and "-" in dt and ":" in dt:
                ymd, hm = dt.split(" ")
                y, m, d = map(int, ymd.split("-"))
                hour, minute = map(int, hm.split(":"))
                import pytz
                tz = pytz.timezone('Asia/Seoul')
                return datetime(y, m, d, hour, minute, tzinfo=tz)
        except Exception:
            return None
        return None

    async def parse_article(self, page: Page, url: str, card_published_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """기사 상세 정보 파싱 (본문, 제목, 발행일, 기자명, 이미지 등)"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
            await page.wait_for_selector(self.config.article_selector, timeout=self.config.page_timeout)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            from rich.console import Console
            console = Console()
            # 제목
            title_el = soup.select_one(self.config.title_selector)
            title = title_el.get_text(strip=True) if title_el else None
            if not title or len(title) < self.config.min_title_length:
                return None
            # 본문
            article_area = soup.select_one(self.config.article_selector)
            content = None
            if article_area:
                for unwanted in article_area.select("script, style, .ad, .advertisement"):
                    unwanted.decompose()
                content = article_area.get_text(strip=True)
            if not content or len(content) < self.config.min_content_length:
                return None
            # 발행일(상세)
            date_el = soup.select_one(self.config.date_selector)
            published_at = None
            if date_el:
                li_tags = date_el.find_all('li')
                for li in li_tags:
                    txt = li.get_text(strip=True)
                    if '등록' in txt or '발행' in txt:
                        published_at = txt
                        break
            # 카드에서 받은 published_at 백업
            if not published_at and card_published_at:
                published_at = card_published_at
            published_at_dt = self.parse_date_string(published_at)
            console.print(f"[cyan]상세 파싱: card_published_at={card_published_at}, published_at={published_at}, published_at_dt={published_at_dt} ({url})[/cyan]")
            if not published_at_dt:
                return None
            # 기자명
            author_el = soup.select_one(self.config.author_selector)
            author = author_el.get_text(strip=True) if author_el else None
            # 이미지
            image_el = soup.select_one(self.config.image_selector)
            image_url = image_el['src'] if image_el and image_el.has_attr('src') else None
            return {
                "title": title,
                "url": url,
                "content_full": content,
                "published_at": published_at_dt,
                "author": author,
                "image_url": image_url
            }
        except Exception as e:
            return None

    async def save_to_supabase(self, articles: List[Dict[str, Any]]) -> int:
        """Supabase articles 테이블에 기사 저장 (중복 URL unique constraint 자동 방지)"""
        try:
            article_models = []
            for article_dict in articles:
                published_at = article_dict.get('published_at')
                # published_at 파싱 (날짜 문자열이 있으면 datetime 변환 시도)
                if published_at and isinstance(published_at, str):
                    try:
                        published_at = published_at.replace('등록 ', '').replace('발행 ', '').replace('수정 ', '').replace('.', '-').replace(' ', 'T')
                        # 예: 2025-07-14T11:48
                        if 'T' in published_at:
                            published_at = published_at + ':00' if len(published_at) == 16 else published_at
                        from datetime import datetime
                        published_at = datetime.fromisoformat(published_at)
                    except Exception:
                        published_at = None
                bias = article_dict.get('bias') or 'center-left'
                article_model = Article(
                    title=article_dict['title'],
                    url=article_dict['url'],
                    category='경제',
                    content_full=article_dict.get('content_full'),
                    published_at=published_at,
                    author=article_dict.get('author'),
                    image_url=article_dict.get('image_url'),
                    bias=bias,
                    media_id=article_dict.get('media_id'),
                )
                article_models.append(article_model)
            saved_count = await self.article_service.save_articles(article_models)
            return saved_count
        except Exception as e:
            # DB 저장 실패 시 0 반환
            return 0

    # BaseNewsCrawler 추상 메서드 더미 구현 (필수)
    async def crawl_category(self, *args, **kwargs):
        return []
    async def crawl_all_categories(self, *args, **kwargs):
        return []
    async def run_pipeline(self, *args, **kwargs):
        return None

    async def run(self):
        """전체 파이프라인 실행: 기사 리스트 추출→상세 파싱→Supabase 저장, rich 피드백 포함 (상세화, 30개 채울 때까지 반복)"""
        console = Console()
        category = HaniCategory.ECONOMY
        articles: list = []
        success_count = 0
        fail_count = 0
        skip_count = 0
        max_pages = 10
        min_count = 30
        console.print("\n[bold cyan]🚀 한겨레신문 경제 크롤러 시작[/bold cyan]")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                console.print(f"[yellow]📰 {category.value} 카테고리 기사 리스트 수집 시작...[/yellow]")
                article_cards = []
                page_try = 1
                while len(articles) < min_count and page_try <= max_pages:
                    article_cards = await self.fetch_article_list(browser, category, min_count=min_count, max_pages=page_try)
                    context = await browser.new_context()
                    semaphore = asyncio.Semaphore(5)
                    async def parse_one(card):
                        async with semaphore:
                            page = await context.new_page()
                            try:
                                article = await self.parse_article(page, card["url"], card.get("card_published_at"))
                                if article:
                                    article['media_id'] = await self.get_media_id('한겨레신문')
                                    article['bias'] = await self.get_media_bias('한겨레신문')
                                return article
                            finally:
                                await page.close()
                    articles = []
                    success_count = 0
                    fail_count = 0
                    skip_count = 0
                    with Progress(
                        SpinnerColumn(),
                        BarColumn(),
                        TextColumn("{task.description}"),
                        TimeElapsedColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task(f"[cyan]{page_try}페이지까지 기사 상세 파싱 중...", total=len(article_cards))
                        tasks = [parse_one(card) for card in article_cards]
                        for f in asyncio.as_completed(tasks):
                            article = await f
                            if article:
                                articles.append(article)
                                success_count += 1
                                if len(articles) >= min_count:
                                    break
                            else:
                                skip_count += 1
                            progress.update(task, advance=1)
                    await context.close()
                    if len(articles) >= min_count:
                        break
                    page_try += 1
                console.print(f"[blue]🔎 파싱 성공: {success_count}건, 스킵: {skip_count}건[/blue]")
                if not articles:
                    console.print("[red]❌ 유효한 기사 파싱 결과가 없습니다.[/red]")
                    return
                console.print("[yellow]💾 Supabase DB 저장 시도 중...[/yellow]")
                try:
                    saved_count = await self.save_to_supabase(articles[:min_count])
                    if saved_count > 0:
                        console.print(f"[bold green]✅ {saved_count}개 기사 DB 저장 완료 (중복 제외)[/bold green]")
                        if saved_count < len(articles[:min_count]):
                            console.print(f"[yellow]⚠️ {len(articles[:min_count])-saved_count}개는 이미 DB에 존재하여 저장되지 않음[/yellow]")
                    else:
                        console.print("[red]❌ DB 저장 실패 또는 중복 기사만 존재[/red]")
                except Exception as e:
                    console.print(f"[red]❌ DB 저장 중 예외 발생: {e}[/red]")
                console.print(f"[bold magenta]🎉 전체 파이프라인 완료![/bold magenta] (총 파싱: {len(articles[:min_count])}건, DB 저장: {saved_count}건)")
        except Exception as e:
            console.print(f"[red]❌ 크롤링 중 예외 발생: {e}[/red]")

    async def get_media_id(self, media_name: str) -> str:
        # ArticleService의 get_or_create_media 활용
        media_info = await self.article_service.get_or_create_media(media_name)
        if media_info and media_info.get('id'):
            return media_info['id']
        # 안전한 기본값(UUID 형식)
        return '00000000-0000-0000-0000-000000000000'

    async def get_media_bias(self, media_name: str) -> str:
        media_info = await self.article_service.get_or_create_media(media_name)
        if media_info and media_info.get('bias'):
            return media_info['bias']
        return 'center-left'

    async def save_articles(self, *args, **kwargs):
        return 0

async def main():
    config = HaniCrawlerConfig()
    crawler = HaniCrawler(config)
    await crawler.run()

# 직접 실행 시: 비동기 main 함수
if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 