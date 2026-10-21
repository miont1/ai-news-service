import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser

from app.api.schemas import NewsItemCreate

SEMAPHORE = asyncio.Semaphore(10)


async def fetch_raw_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch full article content using trafilatura."""
    if not url:
        return ""
    async with SEMAPHORE:
        try:
            response = await client.get(url, follow_redirects=True, timeout=10.0)
            response.raise_for_status()
            text = trafilatura.extract(response.text) or ""
            return text
        except Exception as e:
            print(f"Error fetching text for {url}: {e}")
            return ""


def extract_rss_url(item) -> str:
    """Extract item URL checking guid, link href and link inner/next text."""
    guid = item.css_first("guid")
    if guid and guid.text(strip=True):
        return guid.text(strip=True)

    link = item.css_first("link")
    if link:
        if link.attributes.get("href"):
            return link.attributes["href"].strip()
        if link.text(strip=True):
            return link.text(strip=True)
        # Lexbor HTML parser treats <link> as void, putting enclosed text in link.next
        if link.next and link.next.text(strip=True):
            return link.next.text(strip=True)

    return ""


def parse_rss_item(item, feed_url: str) -> NewsItemCreate:
    """Parse single RSS item without loading raw_text yet."""
    title_node = item.css_first("title")
    summary_node = item.css_first("description")
    pub_date_node = item.css_first("pubDate")

    title = title_node.text(strip=True) if title_node else ""
    url = extract_rss_url(item)
    summary = summary_node.text(strip=True) if summary_node else ""

    if pub_date_node and pub_date_node.text(strip=True):
        try:
            published_at = parsedate_to_datetime(pub_date_node.text(strip=True))
        except (ValueError, TypeError):
            published_at = datetime.now(UTC)
    else:
        published_at = datetime.now(UTC)

    return NewsItemCreate(
        title=title,
        url=url,
        summary=summary,
        source=feed_url,
        published_at=published_at,
        raw_text=None,
    )


async def fetch_rss_feed(feed_url: str) -> list[NewsItemCreate]:
    """Fetch and parse RSS feed items (metadata only)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(feed_url, follow_redirects=True)
        response.raise_for_status()

        tree = LexborHTMLParser(response.text)
        items = tree.css("item")
        return [parse_rss_item(item, feed_url) for item in items]


async def populate_articles_raw_text(items: list[NewsItemCreate]) -> list[NewsItemCreate]:
    """Fetch raw_text concurrently for a list of filtered and verified items."""
    if not items:
        return []

    async with httpx.AsyncClient(timeout=15.0) as client:
        async def _populate(item: NewsItemCreate):
            if item.url:
                item.raw_text = await fetch_raw_text(client, item.url)
            return item

        tasks = [_populate(item) for item in items]
        return await asyncio.gather(*tasks)
