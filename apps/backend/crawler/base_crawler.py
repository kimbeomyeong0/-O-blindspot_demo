from abc import ABC, abstractmethod

class BaseNewsCrawler(ABC):
    @abstractmethod
    async def crawl_category(self, browser, category):
        pass

    @abstractmethod
    async def crawl_all_categories(self):
        pass

    @abstractmethod
    async def save_articles(self, articles):
        pass 