import asyncio
from typing import List, Dict, Optional, Set
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Browser
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel

from apps.backend.app.services.article_service import ArticleService
from apps.backend.app.models.article import Article

console = Console()

BASE_URL = "https://www.ohmynews.com"
CATEGORY = "경제"
CATEGORY_CODE = "C0300"
MEDIA_NAME = "오마이뉴스"

# 페이지 URL 패턴
PAGE_URLS = [
    f"/NWS_Web/ArticlePage/Total_Article.aspx?PAGE_CD={CATEGORY_CODE}",
    f"/NWS_Web/Articlepage/Total_Article.aspx?PAGE_CD={CATEGORY_CODE}&pageno={{}}"  # 2페이지~
]

class OhmynewsEconomyCrawler:
    def __init__(self, articles_per_category: int = 30):
        self.articles_per_category = articles_per_category
        self.article_service = ArticleService()
        self.media_id = None
        self.bias = None

    async def _get_media_info(self):
        info = await self.article_service.get_or_create_media(MEDIA_NAME)
        if info:
            self.media_id = info.get("id")
            self.bias = info.get("bias", "center")
        else:
            self.media_id = "149dab80-d623-49d7-a0f2-4c52329d2626"
            self.bias = "center"

    async def fetch_article_list(self, browser: Browser) -> List[Dict]:
        articles: List[Dict] = []
        seen_urls: Set[str] = set()
        page_num = 1
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"[bold blue]오마이뉴스 경제 기사 수집", total=self.articles_per_category)
            while len(articles) < self.articles_per_category:
                if page_num == 1:
                    url = urljoin(BASE_URL, PAGE_URLS[0])
                else:
                    url = urljoin(BASE_URL, PAGE_URLS[1].format(page_num))
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                ul = soup.find("ul", class_="list_type1")
                if not ul or not hasattr(ul, 'find_all'):
                    await page.close()
                    break
                li_tags = ul.find_all("li", recursive=False)
                li_tags = [li for li in li_tags if isinstance(li, Tag)]
                for li in li_tags:
                    try:
                        cont = li.find("div", class_="cont") if hasattr(li, 'find') else None
                        if not (cont and isinstance(cont, Tag)):
                            continue
                        dt = cont.find("dt") if hasattr(cont, 'find') else None
                        a_tag = dt.find("a") if dt and hasattr(dt, 'find') else None
                        if not (a_tag and isinstance(a_tag, Tag)):
                            url_path = None
                        else:
                            url_path = a_tag["href"] if a_tag.has_attr("href") and isinstance(a_tag["href"], str) else None
                        article_url = urljoin(BASE_URL, url_path) if url_path and isinstance(url_path, str) else None
                        if not article_url or article_url in seen_urls:
                            continue
                        title = a_tag.get_text(strip=True) if a_tag and hasattr(a_tag, 'get_text') else None
                        dd = cont.find("dd") if hasattr(cont, 'find') else None
                        summary = dd.get_text(strip=True) if dd and isinstance(dd, Tag) and hasattr(dd, 'get_text') else None
                        thumb = li.find("p", class_="thumb") if hasattr(li, 'find') else None
                        img_tag = thumb.find("img") if thumb and hasattr(thumb, 'find') else None
                        image_url = img_tag["src"] if img_tag and isinstance(img_tag, Tag) and img_tag.has_attr("src") and isinstance(img_tag["src"], str) else None
                        source = cont.find("p", class_="source") if hasattr(cont, 'find') else None
                        author = None
                        published_at = None
                        if source and isinstance(source, Tag):
                            author_tag = source.find("a")
                            author = author_tag.get_text(strip=True) if author_tag and hasattr(author_tag, 'get_text') else None
                            spans = source.find_all("span") if hasattr(source, 'find_all') else []
                            spans = [sp for sp in spans if isinstance(sp, Tag)]
                            for i, sp in enumerate(spans):
                                if hasattr(sp, 'get') and "bar1" in sp.get("class", []):
                                    if i+1 < len(spans) and hasattr(spans[i+1], 'get_text') and isinstance(spans[i+1], Tag):
                                        published_at = spans[i+1].get_text(strip=True)
                        detail = await self.parse_article(browser, article_url)
                        article = {
                            "title": title or detail.get("title"),
                            "url": article_url,
                            "category": CATEGORY,
                            "summary": summary,
                            "content_full": detail.get("content_full"),
                            "published_at": detail.get("published_at") or published_at,
                            "author": author or detail.get("author"),
                            "image_url": image_url or detail.get("image_url"),
                        }
                        articles.append(article)
                        seen_urls.add(article_url)
                        progress.update(task, advance=1)
                        if len(articles) >= self.articles_per_category:
                            break
                    except Exception:
                        continue
                await page.close()
                page_num += 1
        return articles[:self.articles_per_category]

    def extract_published_at(self, soup):
        # 문서 전체에서 모든 <span class="date"> 추출
        if not isinstance(soup, Tag):
            return None
        date_spans = [sp for sp in soup.find_all("span", class_="date") if isinstance(sp, Tag)]
        for sp in date_spans:
            txt = sp.get_text(strip=True)
            if txt and "최종 업데이트" not in txt and ":" in txt:
                dt = self.parse_date_string(txt)
                if dt:
                    return dt
        return None

    def parse_date_string(self, dt):
        try:
            # 25.07.14 19:06
            if "." in dt and ":" in dt:
                y, m, d_hm = dt.split(".")
                d, hm = d_hm.strip().split(" ")
                year = int(y)
                if year < 100:
                    year += 2000
                hour, minute = map(int, hm.split(":"))
                import pytz
                tz = pytz.timezone('Asia/Seoul')
                return datetime(year, int(m), int(d), hour, minute, tzinfo=tz)
        except Exception:
            return None
        return None

    async def parse_article(self, browser: Browser, url: str) -> Dict:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            # 제목
            title_tag = soup.find("h2", class_="title")
            title = title_tag.get_text(strip=True) if title_tag and isinstance(title_tag, Tag) and hasattr(title_tag, 'get_text') else None
            # robust 날짜 추출
            published_at = self.extract_published_at(soup)
            author = None
            cat_div2 = soup.find("div", class_="atc-sponsor")
            if cat_div2 and hasattr(cat_div2, 'find'):
                a_tag = cat_div2.find("a")
                if a_tag and isinstance(a_tag, Tag) and hasattr(a_tag, 'get_text'):
                    author = a_tag.get_text(strip=True)
            content = None
            atc_view = soup.find("div", class_="atc_view2025")
            if atc_view and hasattr(atc_view, 'find'):
                at_contents = atc_view.find("div", class_="at_contents")
                if at_contents and isinstance(at_contents, Tag) and hasattr(at_contents, 'find_all'):
                    divs = at_contents.find_all("div", recursive=True)
                    divs = [ad for ad in divs if isinstance(ad, Tag)]
                    for ad in divs:
                        if hasattr(ad, 'decompose'):
                            ad.decompose()
                    if hasattr(at_contents, 'decode_contents'):
                        content = at_contents.decode_contents().strip()
            image_url = None
            if atc_view and hasattr(atc_view, 'find'):
                img_tag = atc_view.find("img")
                if img_tag and isinstance(img_tag, Tag) and img_tag.has_attr("src") and isinstance(img_tag["src"], str):
                    image_url = img_tag["src"]
            return {
                "title": title,
                "content_full": content,
                "published_at": published_at,
                "author": author,
                "image_url": image_url
            }
        except Exception:
            return {}
        finally:
            await page.close()

    async def run(self):
        await self._get_media_info()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            articles = await self.fetch_article_list(browser)
            # Article 객체 변환
            article_objs = []
            skipped = 0
            for art in articles:
                published_at = art.get("published_at")
                if not published_at:
                    console.print(Panel(f"[yellow]날짜 누락: {art.get('url')}[/yellow]", title="[bold red]경고: 날짜 없음[/bold red]"))
                    skipped += 1
                    continue
                article_objs.append(Article(
                    title=art.get("title") or "",
                    url=art.get("url") or "",
                    category=art.get("category") or CATEGORY,
                    content_full=art.get("content_full"),
                    published_at=published_at,
                    author=art.get("author"),
                    image_url=art.get("image_url"),
                    bias=self.bias or "center",
                    media_id=self.media_id
                ))
            saved = await self.article_service.save_articles(article_objs)
            console.print(f"[bold green]성공: {saved}개 저장됨[/bold green] / [bold yellow]날짜 없는 기사 스킵: {skipped}개[/bold yellow] / [bold yellow]실패: {len(article_objs)-saved}개[/bold yellow]")
            await browser.close()

async def main():
    crawler = OhmynewsEconomyCrawler()
    await crawler.run()

if __name__ == "__main__":
    asyncio.run(main())
