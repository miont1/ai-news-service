import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser

from app.api.schemas import NewsItemCreate

SEMAPHORE = asyncio.Semaphore(10)

url = "https://www.radiosvoboda.org/a/news-vyjizd-iz-kyjeva-udar-po-azs-zahyblyj-poraneni/33880013.html"
url2 = "https://www.radiosvoboda.org/api/zrqitl-vomx-tpeoumq/"

async def fetch_raw_text(client: httpx.AsyncClient, url: str) -> str:
    async with SEMAPHORE:
        try:
            response = await client.get(url, follow_redirects=True, timeout=10.0)
            response.raise_for_status()
            text = trafilatura.extract(response.text) or ""
            if not text:
                return ""
            
            return text
        except Exception as e:
            print(f"Error fetching text for {url}: {e}")
            return ""

async def process_item(client: httpx.AsyncClient, item, feed_url: str) -> NewsItemCreate:
    title_node = item.css_first("title")
    url_node = item.css_first("guid")
    summary_node = item.css_first("description")
    pub_date_node = item.css_first("pubDate")
    published_at = None
    title = title_node.text(strip=True) if title_node else ""
    url = url_node.text(strip=True) if url_node else ""
    summary = summary_node.text(strip=True) if summary_node else ""
    if pub_date_node and pub_date_node.text(strip=True):
        try:
            published_at = parsedate_to_datetime(pub_date_node.text(strip=True))
        except Exception:
            published_at = datetime.now(UTC)
    else:
        published_at = datetime.now(UTC)
    raw_text = await fetch_raw_text(client, url)
    item_data = NewsItemCreate(
        title= title,
        url= url,
        summary= summary,
        source= feed_url,
        published_at= published_at,
        raw_text= raw_text,
    )
    return item_data
    
async def fetch_rss_feed(feed_url: str) -> list[NewsItemCreate]:
    async with httpx.AsyncClient() as client:
        response = await client.get(feed_url, follow_redirects=True, timeout=10.0)
        response.raise_for_status()

        tree = LexborHTMLParser(response.text)

        items = tree.css("item")

        tasks = [process_item(client, item, feed_url) for item in items]
        news_items = await asyncio.gather(*tasks)

    return list(news_items)

if __name__ == "__main__":
    print(asyncio.run(fetch_rss_feed(url2)))
