import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import FailedSourceInfo, NewsItemCreate
from app.models import SourceType
from app.news_parser.sites import fetch_rss_feed, populate_articles_raw_text
from app.repositories.keyword_repository import KeywordRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.source_repository import SourceRepository
from app.services.news_filter import filter_relevant_news

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.news_repo = NewsRepository(session)
        self.source_repo = SourceRepository(session)
        self.keyword_repo = KeywordRepository(session)

    async def fetch_and_store_site_news(
        self,
        keywords: list[str] | None = None,
        use_db_keywords: bool = False,
    ) -> dict:
        # 1. Get active sources of type SITE
        sources = await self.source_repo.get_active_sources(SourceType.SITE)
        if not sources:
            return {
                "sources_checked": 0,
                "total_found": 0,
                "relevant_matched": 0,
                "new_saved": 0,
                "message": "No active site sources found in database",
            }

        # 2. Determine keywords filter (use_db_keywords flag takes precedence)
        if use_db_keywords:
            active_keywords = await self.keyword_repo.get_all_words()
        elif keywords:
            active_keywords = [k.strip() for k in keywords if k.strip()]
        else:
            active_keywords = []

        # 3. Fetch RSS feeds concurrently across all sources
        tasks = [fetch_rss_feed(source.url) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[NewsItemCreate] = []
        failed_sources: list[FailedSourceInfo] = []

        for source, res in zip(sources, results):
            if isinstance(res, Exception):
                err_msg = str(res) or type(res).__name__
                logger.warning(
                    "Error fetching RSS feed from %s (%s): %s",
                    source.name,
                    source.url,
                    err_msg,
                )
                failed_sources.append(
                    FailedSourceInfo(
                        source_name=source.name,
                        url=source.url,
                        error=err_msg,
                    )
                )
            else:
                all_items.extend(res)

        if not all_items:
            fail_suffix = f" ({len(failed_sources)} sources failed)" if failed_sources else ""
            return {
                "sources_checked": len(sources),
                "sources_failed": len(failed_sources),
                "total_found": 0,
                "relevant_matched": 0,
                "new_saved": 0,
                "failed_sources": failed_sources,
                "message": f"No items retrieved from sources{fail_suffix}",
            }

        # 4. Filter by keywords in title and summary
        relevant_items = filter_relevant_news(all_items, active_keywords)
        if not relevant_items:
            return {
                "sources_checked": len(sources),
                "sources_failed": len(failed_sources),
                "total_found": len(all_items),
                "relevant_matched": 0,
                "new_saved": 0,
                "failed_sources": failed_sources,
                "message": "None of the found items matched configured keywords",
            }

        # 5. Deduplicate within current batch and against database (by both ID and URL)
        unique_batch_items: dict[str, NewsItemCreate] = {}
        seen_batch_urls: set[str] = set()
        for item in relevant_items:
            if item.url and item.url in seen_batch_urls:
                continue
            if item.id and item.id not in unique_batch_items:
                unique_batch_items[item.id] = item
                if item.url:
                    seen_batch_urls.add(item.url)

        existing_ids = await self.news_repo.get_existing_ids(list(unique_batch_items.keys()))
        batch_urls = [item.url for item in unique_batch_items.values() if item.url]
        existing_urls = await self.news_repo.get_existing_urls(batch_urls)

        new_items = [
            item for item_id, item in unique_batch_items.items()
            if item_id not in existing_ids and (not item.url or item.url not in existing_urls)
        ]

        if not new_items:
            return {
                "sources_checked": len(sources),
                "sources_failed": len(failed_sources),
                "total_found": len(all_items),
                "relevant_matched": len(relevant_items),
                "new_saved": 0,
                "failed_sources": failed_sources,
                "message": "All relevant items already exist in database",
            }

        # 6. Fetch full text (raw_text) ONLY for new relevant items
        items_with_text = await populate_articles_raw_text(new_items)

        # 7. Save to database via repository
        saved_items = await self.news_repo.save_news_items(items_with_text)

        return {
            "sources_checked": len(sources),
            "sources_failed": len(failed_sources),
            "total_found": len(all_items),
            "relevant_matched": len(relevant_items),
            "new_saved": len(saved_items),
            "failed_sources": failed_sources,
            "message": f"Successfully parsed, filtered and saved {len(saved_items)} news items",
        }
