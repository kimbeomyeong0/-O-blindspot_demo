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

# Supabase 연동
# sys.path.append(str(Path(__file__).parent.parent))  # 삭제
from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article
from apps.backend.crawler.base import BaseNewsCrawler
from apps.backend.crawler.utils import dict_to_article

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

logger = logging.getLogger(__name__)

def print_status(msg, status="info"):
    console.print(msg, style=status)

class Category(Enum):
    ECONOMY = "경제"
    # 확장성: 다른 카테고리 추가 가능

@dataclass
class CrawlerConfig:
    max_pages: int = 4  # 1~4페이지 순회(30개 미만시 추가)
    articles_per_category: int = 30
    page_timeout: int = 20000
    wait_timeout: int = 2000
    min_content_length: int = 30
    min_title_length: int = 5

class ConsoleUI:
    @staticmethod
    def print_header():
        console.rule("[bold blue]🚀 프레시안 크롤러 시작")
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

    def _parse_img_url(self, style: str) -> Optional[str]:
        # style="background-image:url('/_resources/10/2025/07/14/2025071415353074636_l.s.jpg')"
        # style이 list면 첫 번째, None이면 빈 문자열
        if isinstance(style, list):
            style = style[0] if style else ""
        if not isinstance(style, str):
            style = ""
        m = re.search(r"background-image:url\(['\"]?(.*?)['\"]?\)", style)
        if m:
            url = m.group(1)
            if url.startswith("/"):
                return f"https://www.pressian.com{url}"
            return url
        return None

    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        # robust: 한글 접두사, 불필요한 문자, 공백 등 제거
        if date_str:
            import re
            date_str = re.sub(r'^(기사입력|입력|수정|등록)[ :\-]*', '', date_str)
            date_str = date_str.replace(".", "-").replace("  ", " ").strip()
            date_str = re.sub(r"[^0-9\- :]+", "", date_str)
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                continue
        return None

    def parse_article_list(self, html: str) -> List[dict]:
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        # 카드 HTML 구조에 맞게 셀렉터 점검
        for li in soup.select('div.section.list_arl_group ul.list > li'):
            try:
                thumb_a = li.select_one('div.thumb a')
                url = None
                if thumb_a:
                    href = thumb_a.get('href')
                    if isinstance(href, list):
                        href = href[0] if href else None
                    if href and isinstance(href, str):
                        url = href if href.startswith('http') else f"https://www.pressian.com{href}"
                if not url:
                    continue
                title_tag = li.select_one('p.title a')
                title = title_tag.get_text(strip=True) if title_tag else None
                if not title:
                    continue
                subtitle_tag = li.select_one('p.sub_title a')
                subtitle = subtitle_tag.get_text(strip=True) if subtitle_tag else None
                summary_tag = li.select_one('p.body a')
                summary = summary_tag.get_text(strip=True) if summary_tag else None
                arl_img = li.select_one('div.arl_img')
                img_style = arl_img['style'] if arl_img and arl_img.has_attr('style') else None
                # img_style을 str로 안전하게 변환
                if isinstance(img_style, list):
                    img_style = img_style[0] if img_style else ""
                if not isinstance(img_style, str):
                    img_style = ""
                image_url = self._parse_img_url(img_style) if img_style else None
                # robust: byline과 date 추출 개선
                byline = li.select_one('div.byline')
                reporter = None
                date = None
                if byline:
                    name_tag = byline.select_one('p.name')
                    date_tag = byline.select_one('p.date')
                    reporter = name_tag.get_text(strip=True) if name_tag else None
                    date = date_tag.get_text(strip=True) if date_tag else None
                    # rich로 카드별 추출된 날짜 디버깅
                    from rich.console import Console
                    console = Console()
                    console.print(f"[magenta]카드 날짜 추출: {date} ({title[:30]}...)[/magenta]")
                articles.append({
                    "url": url,
                    "title": title,
                    "subtitle": subtitle,
                    "summary": summary,
                    "image_url": image_url,
                    "author": reporter,
                    "published_at": date
                })
            except Exception as e:
                from rich.console import Console
                console = Console()
                console.print(f"[red]카드 파싱 오류: {e}[/red]")
                continue
        return articles

    def parse_article_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        # 제목/부제목
        title = None
        subtitle = None
        title_tag = soup.select_one('div.view_header p.title')
        if title_tag:
            title = title_tag.get_text(strip=True)
        subtitle_tag = soup.select_one('div.view_header p.sub_title')
        if subtitle_tag:
            subtitle = subtitle_tag.get_text(strip=True)
        # 기자명/날짜
        byline = soup.select_one('div.byline')
        author = None
        date = None
        if byline:
            name_tag = byline.select_one('span.name')
            date_tag = byline.select_one('span.date')
            author = name_tag.get_text(strip=True) if name_tag else None
            date = date_tag.get_text(strip=True) if date_tag else None
        # 본문
        body_div = soup.select_one('div.article_body')
        body = ""
        if body_div:
            for tag in body_div.find_all(['p', 'div', 'figure']):
                if tag.name == 'figure':
                    img = tag.find('img')
                    # Tag 타입인지 확인 후 get('src')
                    if img and hasattr(img, 'get'):
                        src = img.get('src')
                        if src:
                            body += f"<img src='{src}' />\n"
                    continue
                text = tag.get_text(strip=True)
                if text:
                    body += text + "\n"
        # 본문 이미지(첫번째)
        image_url = None
        if body_div:
            img_tag = body_div.find('img')
            # Tag 타입인지 명확히 체크
            if img_tag and isinstance(img_tag, Tag):
                src = img_tag.get('src')
                if src:
                    image_url = src
        return {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "published_at": date,
            "content_full": body.strip(),
            "image_url": image_url
        }

class PressianCrawler(BaseNewsCrawler):
    CATEGORY_URLS = {
        Category.ECONOMY: [
            "https://www.pressian.com/pages/news-economy-list",
            "https://www.pressian.com/pages/news-economy-list?page=2",
            "https://www.pressian.com/pages/news-economy-list?page=3",
            "https://www.pressian.com/pages/news-economy-list?page=4"
        ]
    }

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.extractor = ArticleExtractor(config)
        self.article_service = ArticleService()
        self.ui = ConsoleUI()

    async def crawl_category(self, browser: Browser, category: Category) -> List[Dict[str, Any]]:
        articles = []
        seen_urls = set()
        for page_url in self.CATEGORY_URLS[category]:
            page = await browser.new_page()
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=self.config.page_timeout)
                await page.wait_for_timeout(self.config.wait_timeout)
                html = await page.content()
                page_articles = self.extractor.parse_article_list(html)
                for art in page_articles:
                    if art['url'] not in seen_urls:
                        seen_urls.add(art['url'])
                        art['category'] = category.value  # 카테고리 필드 명시적으로 추가
                        articles.append(art)
                if len(articles) >= self.config.articles_per_category:
                    articles = articles[:self.config.articles_per_category]
                    break
            finally:
                await page.close()
        return articles

    async def enrich_and_parse_details(self, browser: Browser, articles: List[dict]) -> List[dict]:
        enriched = []
        semaphore = asyncio.Semaphore(5)  # 동시에 5개까지
        async def parse_one(art, idx):
            async with semaphore:
                page = await browser.new_page()
                try:
                    await page.goto(art['url'], wait_until="domcontentloaded", timeout=self.config.page_timeout)
                    await page.wait_for_timeout(self.config.wait_timeout)
                    html = await page.content()
                    detail = self.extractor.parse_article_detail(html)
                    # 카드에서 받은 published_at 백업 사용
                    card_published_at = art.get('published_at')
                    detail_published_at = detail.get('published_at')
                    from rich.console import Console
                    console = Console()
                    console.print(f"[yellow]상세 파싱: 카드={card_published_at}, 상세={detail_published_at} ({art['title'][:30]}...)[/yellow]")
                    # 상세 날짜를 datetime으로 변환 시도
                    if detail_published_at:
                        detail_published_at_dt = self.extractor._parse_datetime(detail_published_at)
                        if detail_published_at_dt:
                            detail['published_at'] = detail_published_at_dt
                            console.print(f"[green]상세 파싱: 상세 날짜 변환 성공 - {detail_published_at_dt} ({art['title'][:30]}...)[/green]")
                        else:
                            # 상세 날짜 변환 실패 시 카드 날짜 사용
                            if card_published_at:
                                card_published_at_dt = self.extractor._parse_datetime(card_published_at)
                                if card_published_at_dt:
                                    detail['published_at'] = card_published_at_dt
                                    console.print(f"[cyan]상세 파싱: 카드 날짜 백업 사용 - {card_published_at_dt} ({art['title'][:30]}...)[/cyan]")
                                else:
                                    detail['published_at'] = None
                                    console.print(f"[red]상세 파싱: 날짜 변환 실패 - {art['title'][:30]}...)[/red]")
                            else:
                                detail['published_at'] = None
                                console.print(f"[red]상세 파싱: 날짜 없음 - {art['title'][:30]}...)[/red]")
                    elif card_published_at:
                        # 상세에 날짜가 없으면 카드 날짜 사용
                        card_published_at_dt = self.extractor._parse_datetime(card_published_at)
                        if card_published_at_dt:
                            detail['published_at'] = card_published_at_dt
                            console.print(f"[cyan]상세 파싱: 카드 날짜 백업 사용 - {card_published_at_dt} ({art['title'][:30]}...)[/cyan]")
                        else:
                            detail['published_at'] = None
                            console.print(f"[red]상세 파싱: 카드 날짜 변환 실패 - {art['title'][:30]}...)[/red]")
                    else:
                        detail['published_at'] = None
                        console.print(f"[red]상세 파싱: 날짜 없음 - {art['title'][:30]}...)[/red]")
                    merged = {**art, **{k: v for k, v in detail.items() if v}}
                    print_status(f"✔ {art['title'][:40]} ... 성공", "success")
                    return merged
                except Exception as e:
                    print_status(f"✖ {art['title'][:40]} ... 오류: {e}", "fail")
                    return None
                finally:
                    await page.close()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"상세 기사 파싱 중...", total=len(articles))
            tasks = [parse_one(art, i) for i, art in enumerate(articles, 1)]
            for f in asyncio.as_completed(tasks):
                result = await f
                if result:
                    enriched.append(result)
                progress.update(task, advance=1)
        return enriched

    async def crawl_all_categories(self, test_mode: bool = False) -> List[Dict[str, Any]]:
        self.ui.print_header()
        all_articles = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for category in Category:
                    self.ui.print_category_start(category.value)
                    articles = await self.crawl_category(browser, category)
                    if not articles:
                        continue
                    articles = await self.enrich_and_parse_details(browser, articles)
                    self.ui.print_category_complete(category.value, len(articles))
                    all_articles.extend(articles)
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
        filename = f"pressian_articles_{timestamp}.jsonl"
        filepath = data_dir / filename
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            for article in articles:
                # datetime 객체를 JSON 직렬화 가능한 형태로 변환
                article_copy = article.copy()
                if article_copy.get('published_at') and isinstance(article_copy['published_at'], datetime):
                    article_copy['published_at'] = article_copy['published_at'].isoformat()
                await f.write(json.dumps(article_copy, ensure_ascii=False) + '\n')
        return str(filepath)

    async def save_articles_to_db(self, articles: List[Dict[str, Any]]) -> int:
        if not articles:
            logger.warning("저장할 기사가 없습니다.")
            return 0
        # media_id, bias 자동 조회/할당
        for art in articles:
            media_info = await self.article_service.get_or_create_media("프레시안")
            art['media_id'] = media_info['id'] if media_info else None
            art['bias'] = media_info['bias'] if media_info else 'center'
            # published_at datetime robust 변환 (이미 datetime이면 변환하지 않음)
            if art.get('published_at'):
                if isinstance(art['published_at'], datetime):
                    # 이미 datetime 객체이면 그대로 사용
                    pass
                elif isinstance(art['published_at'], str):
                    # 문자열인 경우에만 파싱 시도
                    try:
                        parsed_dt = self.extractor._parse_datetime(art['published_at'])
                        if parsed_dt:
                            art['published_at'] = parsed_dt
                        else:
                            print_status(f"[경고] 날짜 파싱 실패: {art.get('title')} / 원본: {art.get('published_at')}", "fail")
                            art['published_at'] = None
                    except Exception:
                        print_status(f"[경고] 날짜 파싱 예외: {art.get('title')}", "fail")
                        art['published_at'] = None
                else:
                    # 다른 타입인 경우 None으로 설정
                    art['published_at'] = None
        # Article 모델로 변환
        article_objects = [dict_to_article(art) for art in articles]
        saved_count = await self.article_service.save_articles(article_objects)
        return saved_count

# 전체 파이프라인 실행 예시(main)
async def main():
    config = CrawlerConfig()
    crawler = PressianCrawler(config)
    articles = await crawler.crawl_all_categories()
    if articles:
        filepath = await crawler.save_articles(articles)
        saved_count = await crawler.save_articles_to_db(articles)
        ConsoleUI.print_summary(len(articles), filepath)
        print_status(f"DB 저장: {saved_count}건", "success")
    else:
        print_status("수집된 기사가 없습니다.", "fail")

if __name__ == "__main__":
    asyncio.run(main()) 