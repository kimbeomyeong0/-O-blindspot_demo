from typing import List, Optional
from ..db.supabase_client import supabase_client
from ..models.article import Article
import logging

logger = logging.getLogger(__name__)

class ArticleService:
    def __init__(self):
        self.client = supabase_client.get_client()
    
    async def save_articles(self, articles: List[Article]) -> int:
        """기사들을 데이터베이스에 저장"""
        if not articles:
            return 0
        
        try:
            # 기존 URL 체크를 위한 쿼리
            urls = [article.url for article in articles]
            existing_articles = self.client.table("articles").select("url").in_("url", urls).execute()
            existing_urls = {row["url"] for row in existing_articles.data}
            
            # 중복되지 않은 기사만 필터링
            new_articles = [article for article in articles if article.url not in existing_urls]
            
            if not new_articles:
                logger.info("모든 기사가 이미 존재합니다.")
                return 0
            
            # 조선일보 미디어 ID 가져오기 (없으면 생성)
            media_id = await self._get_or_create_chosun_media()
            
            # 기사 데이터 준비
            articles_data = []
            for article in new_articles:
                article_dict = article.to_dict()
                article_dict["media_id"] = media_id
                articles_data.append(article_dict)
            
            # 일괄 삽입
            result = self.client.table("articles").insert(articles_data).execute()
            
            saved_count = len(result.data) if result.data else 0
            logger.info(f"✅ {saved_count}개 기사 저장 완료")
            
            return saved_count
            
        except Exception as e:
            logger.error(f"기사 저장 중 오류 발생: {e}")
            raise
    
    async def _get_or_create_chosun_media(self) -> str:
        """조선일보 미디어 정보 가져오기 (없으면 생성)"""
        try:
            # 기존 조선일보 미디어 정보 확인
            result = self.client.table("media_outlets").select("id").eq("name", "조선일보").execute()
            
            if result.data:
                return result.data[0]["id"]
            
            # 없으면 생성
            media_data = {
                "name": "조선일보",
                "bias": "center",  # 기본값
                "logo_url": "https://www.chosun.com/favicon.ico"
            }
            
            result = self.client.table("media_outlets").insert(media_data).execute()
            return result.data[0]["id"]
            
        except Exception as e:
            logger.error(f"미디어 정보 처리 중 오류: {e}")
            raise
    
    async def get_articles_by_category(self, category: str, limit: int = 30) -> List[dict]:
        """카테고리별 기사 조회"""
        try:
            result = self.client.table("articles").select("*").eq("category", category).limit(limit).execute()
            return result.data
        except Exception as e:
            logger.error(f"기사 조회 중 오류: {e}")
            return []
    
    async def get_total_articles_count(self) -> int:
        """전체 기사 수 조회"""
        try:
            result = self.client.table("articles").select("id").execute()
            return len(result.data) if result.data else 0
        except Exception as e:
            logger.error(f"기사 수 조회 중 오류: {e}")
            return 0 

    async def get_or_create_media(self, name: str) -> Optional[dict]:
        """언론사 이름으로 media_outlets의 id, bias를 조회(없으면 생성)"""
        try:
            result = self.client.table("media_outlets").select("id,bias").eq("name", name).execute()
            if result.data:
                return {"id": result.data[0]["id"], "bias": result.data[0]["bias"]}
            # 없으면 생성 (bias는 right로 기본값, logo_url은 빈 문자열)
            media_data = {"name": name, "bias": "right", "logo_url": ""}
            result = self.client.table("media_outlets").insert(media_data).execute()
            return {"id": result.data[0]["id"], "bias": result.data[0]["bias"]}
        except Exception as e:
            logger.error(f"미디어 정보 처리 중 오류: {e}")
            return None 