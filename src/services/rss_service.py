"""RSS feed ingestion service for AI news aggregation."""

import re
from datetime import datetime
from time import mktime

import feedparser

from src.core.config import settings
from src.models.schemas import FeedItem

DEFAULT_AI_FEEDS: list[dict[str, str]] = [
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "name": "MIT Technology Review AI",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    },
    {
        "name": "ArXiv AI Recent",
        "url": "https://rss.arxiv.org/rss/cs.AI",
    },
    {
        "name": "Hacker News AI",
        "url": "https://hnrss.org/newest?q=AI",
    },
]


class RssService:
    """Fetches and normalizes news entries from configured RSS feeds."""

    def __init__(self, feeds: list[dict[str, str] | str] | None = None) -> None:
        self.feeds = feeds or getattr(settings, "rss_feeds", DEFAULT_AI_FEEDS)

    def clean_html(self, raw_html: str) -> str:
        """Strip HTML tags and condense whitespace."""
        if not raw_html:
            return ""
        text = re.sub(r"<[^>]+>", " ", raw_html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def parse_feed_date(self, entry: feedparser.FeedParserDict) -> datetime | None:
        """Extract published or updated datetime from feed entry."""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime.fromtimestamp(mktime(entry.published_parsed))
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            return datetime.fromtimestamp(mktime(entry.updated_parsed))
        return None

    def fetch_all_feeds(self) -> list[FeedItem]:
        """Iterate over all feeds, parse entries, and return normalized items."""
        items: list[FeedItem] = []

        for feed_info in self.feeds:
            if isinstance(feed_info, str):
                feed_url = feed_info.strip()
                source_name = feed_url.split("/")[2] if "//" in feed_url else "RSS Feed"
            elif isinstance(feed_info, dict):
                feed_url = str(feed_info.get("url", "")).strip()
                source_name = str(
                    feed_info.get("name")
                    or (feed_url.split("/")[2] if "//" in feed_url else "RSS Feed")
                )
            else:
                continue

            if not feed_url:
                continue

            try:
                parsed = feedparser.parse(feed_url)
                for entry in parsed.entries:
                    title = getattr(entry, "title", "").strip()
                    link = getattr(entry, "link", "").strip()
                    if not title or not link:
                        continue

                    raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                    summary = self.clean_html(raw_summary)
                    pub_date = self.parse_feed_date(entry)

                    items.append(
                        FeedItem(
                            title=title,
                            link=link,
                            summary=summary,
                            source=source_name,
                            published_at=pub_date,
                        )
                    )
            except Exception:
                # Continue processing remaining feeds if one fails
                continue

        return items
