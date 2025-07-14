from app.models.article import Article
from dateutil.parser import parse as dtparse

def dict_to_article(art: dict) -> Article:
    published_at = art.get("published_at")
    if published_at and isinstance(published_at, str):
        try:
            published_at = dtparse(published_at)
        except Exception:
            published_at = None
    return Article(
        title=art.get("title", ""),
        url=art.get("url", ""),
        category=art.get("category", ""),
        content_full=art.get("content_full"),
        published_at=published_at,
        author=art.get("author"),
        image_url=art.get("image_url"),
        bias=art.get("bias", "right"),
        media_id=art.get("media_id")
    ) 