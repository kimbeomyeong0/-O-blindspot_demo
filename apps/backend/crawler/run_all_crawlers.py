import asyncio
from crawler.crawler_chosun import ChosunCrawler, CrawlerConfig as ChosunConfig
from crawler.crawler_joongang import JoongangCrawler, CrawlerConfig as JoongangConfig
from crawler.crawl_jtbc import JTBCNewsCrawler, CrawlerConfig
# 앞으로 추가될 크롤러들도 여기에 import

async def run_all_crawlers():
    chosun_config = ChosunConfig()
    joongang_config = JoongangConfig()
    jtbc_config = CrawlerConfig()  # JTBC용 설정
    
    crawlers = [
        ChosunCrawler(chosun_config),
        JoongangCrawler(joongang_config),
        JTBCNewsCrawler(jtbc_config),
        # 앞으로 13개 크롤러도 여기에 추가
    ]
    
    print("🚀 모든 크롤러 동시 실행 시작")
    print("=" * 60)
    
    results = await asyncio.gather(*(c.crawl_all_categories() for c in crawlers))
    
    # 결과 통합 및 통계
    total_articles = sum(len(result) for result in results if result)
    print(f"\n🎉 모든 크롤러 완료!")
    print(f"📊 총 {total_articles}개 기사 수집")
    print("=" * 60)
    
    return results

if __name__ == "__main__":
    asyncio.run(run_all_crawlers()) 