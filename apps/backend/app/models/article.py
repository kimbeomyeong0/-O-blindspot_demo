from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class Article:
    title: str
    url: str
    category: str
    content_full: Optional[str] = None
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    bias: str = "center"  # 기본값은 중립
    media_id: Optional[str] = None  # media_outlets 테이블의 id
    
    def to_dict(self) -> dict:
        """Supabase에 저장할 딕셔너리 형태로 변환"""
        return {
            "title": self.title,
            "url": self.url,
            "category": self.category,
            "content_full": self.content_full,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "author": self.author,
            "image_url": self.image_url,
            "bias": self.bias,
            "media_id": self.media_id
        } 