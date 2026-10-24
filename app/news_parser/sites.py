import asyncio
import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser

from app.api.schemas import NewsItemCreate

logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(10)

ACCORDION_BUTTON_WORDS = {
    "БІЛЬШЕ",
    "МЕНШЕ",
    "ПОКАЗАТИ БІЛЬШЕ",
    "ПОКАЗАТИ МЕНШЕ",
}

UI_NOISE_WORDS = {
    "форум",
    "коментарі",
    "поділитися",
    "підписатися",
    "читати далі",
    "показати повністю",
    "реклама",
    "стежте за нами",
    "долучайтеся",
    "теги",
}

CROSS_LINK_REGEX = re.compile(
    r"^\s*(?:читайте|дивіться|також читайте|слухайте|більше на тему|більше по темі|вас також може зацікавити)\s*(?:також|ще)?\s*:\s*.+$",
    re.IGNORECASE,
)
MEDIA_TEASER_REGEX = re.compile(
    r"\((?:фоторепортаж|відеорепортаж|відео|інфографіка|онлайн)\)\s*$",
    re.IGNORECASE,
)


def clean_article_text(raw: str) -> str:
    """Clean extracted raw text by removing UI noise, cross-promo links and extra whitespace."""
    if not raw or not raw.strip():
        return ""

    cleaned_lines: list[str] = []
    prev_line_lower: str | None = None

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line_lower = line.lower()

        # Skip repeated consecutive identical lines (e.g. repeated accordions)
        if line_lower == prev_line_lower:
            continue

        # Skip standalone accordion buttons or navigation words
        if line in ACCORDION_BUTTON_WORDS or line_lower in UI_NOISE_WORDS:
            continue

        # Skip inline cross-promo links like "Читайте також: ..."
        if CROSS_LINK_REGEX.match(line):
            continue

        # Skip media teaser links like "... (фоторепортаж)"
        if MEDIA_TEASER_REGEX.search(line):
            continue

        cleaned_lines.append(line)
        prev_line_lower = line_lower

    result = "\n\n".join(cleaned_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


async def fetch_raw_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch full article content using trafilatura with precision filtering and text cleanup."""
    if not url:
        return ""
    async with SEMAPHORE:
        try:
            response = await client.get(url, follow_redirects=True, timeout=10.0)
            response.raise_for_status()
            extracted = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
                deduplicate=True,
                favor_precision=True,
                prune_xpath=["//button", "//*[@role='button']", "//nav", "//footer"],
            ) or ""
            return clean_article_text(extracted)
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as e:
            logger.warning("Error fetching text for %s: %s", url, e)
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
        except (ValueError, TypeError, IndexError):
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
    """Fetch and parse RSS feed items (metadata only).

    Raises:
        httpx.HTTPError: on network or HTTP status failures.
        Exception: on unexpected parsing or content issues.
    """
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
