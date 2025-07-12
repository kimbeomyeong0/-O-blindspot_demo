#!/usr/bin/env python3
"""
테스트용 크롤러
각 언론사에서 카테고리별로 1개씩만 크롤링하여 빠르게 테스트
"""

import asyncio
import sys
import os
from datetime import datetime
from typing import List, Dict

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from apps.backend.app.services.crawler.crawl_chosun import get_articles as get_chosun_articles
from apps.backend.app.services.crawler.crawler_config import CATEGORY_URLS

async def test_chosun_crawler() -> List[Dict]:
    """조선일보 테스트 크롤링"""
    print("=" * 60)
    print("🔍 조선일보 테스트 크롤링 시작")
    print("=" * 60)
    
    # 기존 크롤러 함수를 임시로 수정하여 1개씩만 크롤링
    original_crawler = get_chosun_articles
    
    # 테스트용 크롤러 함수 생성
    async def test_get_chosun_articles():
        """테스트용 조선일보 크롤러 - 카테고리별 1개씩만"""
        from apps.backend.app.services.crawler.crawl_chosun import (
            extract_article_content, clean_text, extract_summary_excerpt
        )
        from apps.backend.app.services.crawler.crawler_config import (
            BROWSER_ARGS, ARTICLE_SELECTORS, MORE_BUTTON_SELECTORS, CONTENT_SELECTORS
        )
        from bs4 import BeautifulSoup
        from playwright.async_api import async_playwright
        from datetime import datetime
        
        all_articles = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=BROWSER_ARGS
            )
            
            for category, urls in CATEGORY_URLS.items():
                try:
                    print(f"📰 조선일보 {category} 카테고리 테스트 중...")
                    
                    # 각 페이지별로 테스트 (첫 번째 기사만)
                    for page_idx, url in enumerate(urls):
                        print(f"   📄 페이지 {page_idx + 1}/{len(urls)}: {url}")
                        
                        page = await browser.new_page()
                        
                        await page.set_extra_http_headers({
                            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                            'Cache-Control': 'no-cache'
                        })
                        
                        # 불필요한 리소스 차단
                        await page.route('**/*.{png,jpg,jpeg,gif,svg,ico,webp,css,woff,woff2,ttf,eot}', 
                                       lambda route: route.abort())
                        
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        
                        html = await page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        
                        # 첫 번째 기사만 찾기
                        article_found = False
                        for selector in ARTICLE_SELECTORS:
                            nodes = soup.select(selector)
                            if nodes:
                                print(f"      ✅ '{selector}' 셀렉터로 {len(nodes)}개 기사 발견")
                                
                                # 첫 번째 기사만 처리
                                node = nodes[0]
                                try:
                                    link = node.get('href')
                                    title = clean_text(node.get_text())
                                    
                                    if not link or not title or len(title) < 3:
                                        print(f"      ❌ 첫 번째 기사 정보 부족: link={link}, title={title}")
                                        continue
                                    
                                    if isinstance(link, list):
                                        link = link[0] if link else ""
                                    
                                    # 상대 경로를 절대 경로로 변환
                                    if link.startswith('/'):
                                        link = f"https://www.chosun.com{link}"
                                    elif not link.startswith('http'):
                                        link = f"https://www.chosun.com/{link}"
                                    
                                    print(f"      📄 기사 제목: {title}")
                                    print(f"      🔗 기사 URL: {link}")
                                    
                                    # 본문 추출
                                    print(f"      📖 본문 추출 중...")
                                    content = await extract_article_content(page, article_url=link)
                                    summary_excerpt = extract_summary_excerpt(content)
                                    
                                    article = {
                                        "issue_id": None,
                                        "media_id": "chosun",
                                        "title": title,
                                        "summary_excerpt": summary_excerpt,
                                        "url": link,
                                        "bias": "right",
                                        "category": category,
                                        "published_at": datetime.now().isoformat(),
                                        "author": None,
                                        "page": page_idx + 1  # 페이지 정보 추가
                                    }
                                    
                                    all_articles.append(article)
                                    article_found = True
                                    print(f"      ✅ {category} 페이지 {page_idx + 1} 테스트 완료 (요약 {len(summary_excerpt)}자)")
                                    break
                                    
                                except Exception as e:
                                    print(f"      ❌ 기사 처리 중 오류: {e}")
                                    continue
                                
                                if article_found:
                                    break
                        
                        if not article_found:
                            print(f"      ❌ {category} 페이지 {page_idx + 1}에서 기사를 찾을 수 없습니다")
                        
                        await page.close()
                        
                        # 모든 페이지를 테스트하므로 break 제거
                        # if article_found:
                        #     break
                    
                    print(f"   ✅ {category} 카테고리 테스트 완료")
                    
                except Exception as e:
                    print(f"❌ 조선일보 {category} 테스트 중 오류: {e}")
                    if 'page' in locals():
                        await page.close()
                    continue
            
            await browser.close()
        
        return all_articles
    
    # 테스트 실행
    articles = await test_get_chosun_articles()
    
    print("\n" + "=" * 60)
    print("📊 조선일보 테스트 결과")
    print("=" * 60)
    
    for article in articles:
        page_info = f" (페이지 {article['page']})" if 'page' in article else ""
        print(f"📰 {article['category']}{page_info}: {article['title'][:50]}...")
        print(f"   🔗 {article['url']}")
        print(f"   📝 요약: {article['summary_excerpt'][:100]}...")
        print()
    
    print(f"✅ 조선일보에서 총 {len(articles)}개 기사 테스트 완료")
    return articles

async def test_all_crawlers():
    """모든 크롤러 테스트"""
    print("🚀 Blindspot 크롤러 테스트 시작")
    print(f"⏰ 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    all_results = {}
    
    # 조선일보 테스트
    try:
        chosun_articles = await test_chosun_crawler()
        all_results['chosun'] = chosun_articles
    except Exception as e:
        print(f"❌ 조선일보 테스트 실패: {e}")
        all_results['chosun'] = []
    
    # 다른 언론사 크롤러가 추가되면 여기에 추가
    # 예: all_results['hani'] = await test_hani_crawler()
    
    print("\n" + "=" * 60)
    print("📊 전체 테스트 결과 요약")
    print("=" * 60)
    
    total_articles = 0
    for media, articles in all_results.items():
        print(f"📰 {media.upper()}: {len(articles)}개 기사")
        total_articles += len(articles)
    
    print(f"\n✅ 총 {total_articles}개 기사 테스트 완료")
    print(f"⏰ 종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return all_results

if __name__ == "__main__":
    print("🎯 Blindspot 크롤러 테스트 도구")
    print("각 언론사에서 카테고리별로 1개씩만 크롤링하여 빠르게 테스트합니다.")
    print()
    
    # 테스트 실행
    results = asyncio.run(test_all_crawlers())
    
    print("\n🎉 테스트 완료!") 