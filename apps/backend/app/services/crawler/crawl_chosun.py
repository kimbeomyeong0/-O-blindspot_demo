import os
import asyncio
from typing import List, Dict
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.async_api import async_playwright
import logging
from .crawler_config import (
    CATEGORY_URLS, 
    BROWSER_ARGS, 
    ARTICLE_SELECTORS, 
    MORE_BUTTON_SELECTORS, 
    CONTENT_SELECTORS
)

logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """텍스트 정리"""
    if not text:
        return ""
    return " ".join(text.strip().split())

def extract_summary_excerpt(content: str, max_length: int = 200) -> str:
    """본문에서 요약 추출"""
    if not content or content == "본문을 추출할 수 없습니다.":
        return ""
    
    # 첫 200자 정도 추출
    summary = content[:max_length].strip()
    
    # 문장 단위로 자르기
    if len(content) > max_length:
        last_period = summary.rfind('.')
        if last_period > max_length * 0.7:  # 70% 이상에서 마침표가 있으면 거기서 자르기
            summary = summary[:last_period + 1]
        else:
            summary += "..."
    
    return summary

async def extract_article_content(page, article_url: str) -> str:
    """조선일보 기사 본문 추출"""
    try:
        await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(500)
        
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        content = ""
        for selector in CONTENT_SELECTORS:
            content_elem = soup.select_one(selector)
            if content_elem:
                content = clean_text(content_elem.get_text())
                if len(content) > 100:
                    break
        
        if not content or len(content.strip()) < 50:
            content = "본문을 추출할 수 없습니다."
            
        return content
        
    except Exception as e:
        logger.error(f"조선일보 본문 추출 실패 - {article_url}: {e}")
        return "본문을 추출할 수 없습니다."

async def get_articles() -> List[Dict]:
    """조선일보 기사 수집"""
    all_articles = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=BROWSER_ARGS
        )
        
        for category, urls in CATEGORY_URLS.items():
            try:
                print(f"🔍 조선일보 {category} 카테고리 크롤링 중...")
                
                count = 0
                target_count = 30
                processed_urls = set()
                
                for url_idx, url in enumerate(urls):
                    if count >= target_count:
                        break
                        
                    try:
                        print(f"📄 조선일보 {category} URL {url_idx + 1}/{len(urls)} 처리 중...")
                        
                        page = await browser.new_page()
                        
                        await page.set_extra_http_headers({
                            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                            'Cache-Control': 'no-cache'
                        })
                        
                        # 불필요한 리소스 차단
                        await page.route('**/*.{png,jpg,jpeg,gif,svg,ico,webp,css,woff,woff2,ttf,eot}', 
                                       lambda route: route.abort())
                        
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        
                        click_count = 0
                        max_clicks = 35
                        
                        while count < target_count and click_count < max_clicks:
                            html = await page.content()
                            soup = BeautifulSoup(html, "html.parser")
                            
                            nodes = []
                            for selector in ARTICLE_SELECTORS:
                                nodes = soup.select(selector)
                                if nodes:
                                    if click_count == 0:
                                        print(f"📄 조선일보 {category} URL {url_idx + 1}에서 '{selector}' 셀렉터로 {len(nodes)}개 요소 발견")
                                    break
                            
                            if not nodes:
                                print(f"❌ 조선일보 {category} URL {url_idx + 1}: 기사 목록을 찾을 수 없습니다")
                                break
                            
                            new_articles_found = 0
                            for node in nodes:
                                if count >= target_count:
                                    break
                                    
                                try:
                                    link = node.get('href')
                                    title = clean_text(node.get_text())
                                    
                                    if not link or not title or len(title) < 3:
                                        continue
                                    
                                    if isinstance(link, list):
                                        link = link[0] if link else ""
                                    
                                    # 상대 경로를 절대 경로로 변환
                                    if link.startswith('/'):
                                        link = f"https://www.chosun.com{link}"
                                    elif not link.startswith('http'):
                                        link = f"https://www.chosun.com/{link}"
                                    
                                    # 중복 제거
                                    if link in processed_urls:
                                        continue
                                    
                                    processed_urls.add(link)
                                    
                                    # 본문 추출
                                    print(f"📄 [{count+1}/{target_count}] {title} - 본문 추출 중...")
                                    content = await extract_article_content(page, article_url=link)
                                    summary_excerpt = extract_summary_excerpt(content)
                                    
                                    # Supabase articles 테이블 형식에 맞춰 반환
                                    article = {
                                        "issue_id": None,
                                        "media_id": "chosun",
                                        "title": title,
                                        "summary_excerpt": summary_excerpt,
                                        "url": link,
                                        "bias": "right",
                                        "category": category,
                                        "published_at": datetime.now().isoformat(),
                                        "author": None
                                    }
                                    
                                    all_articles.append(article)
                                    count += 1
                                    new_articles_found += 1
                                    
                                    print(f"✅ [{count}/{target_count}] {title[:50]}... (요약 {len(summary_excerpt)}자)")
                                    
                                except Exception as e:
                                    print(f"❌ 조선일보 {category} 기사 처리 중 오류: {e}")
                                    continue
                            
                            if new_articles_found == 0 and click_count > 0:
                                print(f"  📄 조선일보 {category} URL {url_idx + 1}: 새로운 기사가 없어 중단")
                                break
                            
                            # 더보기 버튼 찾기 및 클릭
                            try:
                                more_button = None
                                for selector in MORE_BUTTON_SELECTORS:
                                    try:
                                        more_button = page.locator(selector).first
                                        if await more_button.is_visible():
                                            break
                                    except:
                                        continue
                                
                                if more_button and await more_button.is_visible():
                                    print(f"  🔄 조선일보 {category} URL {url_idx + 1}: 더보기 버튼 클릭 ({click_count + 1}번째)")
                                    await more_button.click()
                                    click_count += 1
                                    await page.wait_for_timeout(4000)
                                else:
                                    # 스크롤 시도
                                    print(f"  🔄 조선일보 {category} URL {url_idx + 1}: 스크롤 시도 ({click_count + 1}번째)")
                                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                    await page.wait_for_timeout(3000)
                                    
                                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                    await page.wait_for_timeout(2000)
                                    
                                    new_html = await page.content()
                                    new_soup = BeautifulSoup(new_html, "html.parser")
                                    new_nodes = []
                                    for selector in ARTICLE_SELECTORS:
                                        new_nodes = new_soup.select(selector)
                                        if new_nodes:
                                            break
                                    
                                    if len(new_nodes) <= len(nodes):
                                        print(f"  📄 조선일보 {category} URL {url_idx + 1}: 기사 더보기 버튼을 찾을 수 없어 중단")
                                        break
                                    
                                    click_count += 1
                                    
                            except Exception as e:
                                print(f"  ❌ 조선일보 {category} URL {url_idx + 1}: 더보기 버튼 클릭 중 오류: {e}")
                                break
                        
                        await page.close()
                        print(f"✅ 조선일보 {category} URL {url_idx + 1}에서 {click_count}번 클릭 완료")
                        
                    except Exception as e:
                        print(f"❌ 조선일보 {category} URL {url_idx + 1} 처리 중 오류: {e}")
                        if 'page' in locals():
                            await page.close()
                        continue
                
                print(f"✅ 조선일보 {category}에서 {count}개 기사 수집 완료")
                
            except Exception as e:
                print(f"❌ Error crawling 조선일보 {category}: {e}")
                if 'page' in locals():
                    await page.close()
                continue
        
        await browser.close()
    
    print(f"✅ 조선일보에서 총 {len(all_articles)}개 기사 수집 완료")
    return all_articles

if __name__ == "__main__":
    asyncio.run(get_articles()) 