from .base import Post, BaseCrawler
from .rss import RssCrawler

CRAWLER_REGISTRY: dict[str, type[BaseCrawler]] = {
    "rss": RssCrawler,
}

__all__ = ["Post", "BaseCrawler", "CRAWLER_REGISTRY"]
