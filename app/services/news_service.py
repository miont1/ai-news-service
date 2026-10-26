import asyncio
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import RPCError

from app.ai.ranker import AINewsRanker
from app.api.schemas import FailedSourceInfo, NewsItemCreate
from app.config import settings
from app.models import SourceType
from app.news_parser.exceptions import TelegramParserError
from app.news_parser.sites import fetch_rss_feed, populate_articles_raw_text
from app.news_parser.telegram import (
    fetch_channel_posts,
    get_telegram_client,
)
from app.repositories.keyword_repository import KeywordRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.source_repository import SourceRepository
from app.services.news_filter import filter_relevant_news

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(
        self,
        session: AsyncSession,
        ai_ranker: AINewsRanker | None = None,
    ):
        self.session = session
        self.news_repo = NewsRepository(session)
        self.source_repo = SourceRepository(session)
        self.keyword_repo = KeywordRepository(session)
        self.ai_ranker = ai_ranker or AINewsRanker()

    async def fetch_and_store_site_news(
        self,
        keywords: list[str] | None = None,
        use_db_keywords: bool = False,
        use_ai_filter: bool | None = None,
        top_k: int | None = None,
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

        # 6. AI Ranking & Filtering (select top_k breaking news before scraping raw_text)
        ai_filter_active = (
            use_ai_filter if use_ai_filter is not None else settings.AI_FILTER_ENABLED
        )
        resolved_top_k = top_k if top_k is not None else settings.AI_FILTER_TOP_K

        if ai_filter_active and len(new_items) > resolved_top_k:
            logger.info(
                "Ranking %s candidate site articles with AI to select top %s...",
                len(new_items),
                resolved_top_k,
            )
            new_items = await self.ai_ranker.rank_news(new_items, top_k=resolved_top_k)

        # 7. Fetch full text (raw_text) ONLY for new relevant (and AI-filtered) items
        items_with_text = await populate_articles_raw_text(new_items)

        # 8. Save to database via repository
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

    async def fetch_and_store_telegram_news(
        self,
        limit_per_channel: int = 20,
        min_text_length: int = 200,
        keywords: list[str] | None = None,
        use_db_keywords: bool = False,
        client: Any = None,
        use_ai_filter: bool | None = None,
        top_k: int | None = None,
    ) -> dict:
        """Fetch, filter, deduplicate and store news from active Telegram channels."""
        # 1. Get active sources of type TG
        sources = await self.source_repo.get_active_sources(SourceType.TG)
        if not sources:
            return {
                "sources_checked": 0,
                "sources_failed": 0,
                "total_found": 0,
                "news_found": 0,
                "relevant_matched": 0,
                "new_saved": 0,
                "news_stored": 0,
                "failed_sources": [],
                "message": "No active Telegram sources found in database",
            }

        # 2. Determine keywords filter (use_db_keywords takes precedence)
        if use_db_keywords:
            active_keywords = await self.keyword_repo.get_all_words()
        elif keywords:
            active_keywords = [k.strip() for k in keywords if k.strip()]
        else:
            active_keywords = []

        # 3. Fetch posts concurrently across all Telegram channels
        async def _fetch_all(tg_client: Any) -> list[Any]:
            tasks = [
                fetch_channel_posts(
                    tg_client,
                    source.url,
                    limit=limit_per_channel,
                    min_text_length=min_text_length,
                )
                for source in sources
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        if client is not None:
            results = await _fetch_all(client)
        else:
            try:
                async with get_telegram_client() as tg_client:
                    results = await _fetch_all(tg_client)
            except (TelegramParserError, RPCError, ConnectionError, OSError, ValueError) as conn_err:
                err_msg = str(conn_err) or type(conn_err).__name__
                logger.error("Failed to connect Telegram client: %s", err_msg)
                failed_sources = [
                    FailedSourceInfo(source_name=s.name, url=s.url, error=err_msg)
                    for s in sources
                ]
                return {
                    "sources_checked": len(sources),
                    "sources_failed": len(sources),
                    "total_found": 0,
                    "news_found": 0,
                    "relevant_matched": 0,
                    "new_saved": 0,
                    "news_stored": 0,
                    "failed_sources": failed_sources,
                    "message": f"Telegram client connection error: {err_msg}",
                }

        all_items: list[NewsItemCreate] = []
        failed_sources: list[FailedSourceInfo] = []

        for source, res in zip(sources, results):
            if isinstance(res, Exception):
                err_msg = str(res) or type(res).__name__
                logger.warning(
                    "Error fetching Telegram channel %s (%s): %s",
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
                "news_found": 0,
                "relevant_matched": 0,
                "new_saved": 0,
                "news_stored": 0,
                "failed_sources": failed_sources,
                "message": f"No items retrieved from Telegram sources{fail_suffix}",
            }

        # 5. Filter by keywords in title and summary
        relevant_items = filter_relevant_news(all_items, active_keywords)
        if not relevant_items:
            return {
                "sources_checked": len(sources),
                "sources_failed": len(failed_sources),
                "total_found": len(all_items),
                "news_found": len(all_items),
                "relevant_matched": 0,
                "new_saved": 0,
                "news_stored": 0,
                "failed_sources": failed_sources,
                "message": "None of the found Telegram items matched configured keywords",
            }

        # 6. Deduplicate within current batch and against database (by both ID and URL)
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
            item
            for item_id, item in unique_batch_items.items()
            if item_id not in existing_ids and (not item.url or item.url not in existing_urls)
        ]

        if not new_items:
            return {
                "sources_checked": len(sources),
                "sources_failed": len(failed_sources),
                "total_found": len(all_items),
                "news_found": len(all_items),
                "relevant_matched": len(relevant_items),
                "new_saved": 0,
                "news_stored": 0,
                "failed_sources": failed_sources,
                "message": "All relevant Telegram items already exist in database",
            }

        # 6.5 AI Ranking & Filtering (select top_k breaking posts before saving)
        ai_filter_active = (
            use_ai_filter if use_ai_filter is not None else settings.AI_FILTER_ENABLED
        )
        resolved_top_k = top_k if top_k is not None else settings.AI_FILTER_TOP_K

        if ai_filter_active and len(new_items) > resolved_top_k:
            logger.info(
                "Ranking %s candidate Telegram posts with AI to select top %s...",
                len(new_items),
                resolved_top_k,
            )
            new_items = await self.ai_ranker.rank_news(new_items, top_k=resolved_top_k)

        # 7. Save to database via repository (raw_text is already populated for Telegram)
        saved_items = await self.news_repo.save_news_items(new_items)

        return {
            "sources_checked": len(sources),
            "sources_failed": len(failed_sources),
            "total_found": len(all_items),
            "news_found": len(all_items),
            "relevant_matched": len(relevant_items),
            "new_saved": len(saved_items),
            "news_stored": len(saved_items),
            "failed_sources": failed_sources,
            "message": f"Successfully parsed, filtered and saved {len(saved_items)} news items from Telegram",
        }

    async def fetch_and_rank_pipeline_news(
        self,
        top_k: int | None = None,
        use_db_keywords: bool = False,
        keywords: list[str] | None = None,
        limit_per_channel: int = 20,
        min_text_length: int = 200,
        client: Any = None,
        max_age_hours: int | None = None,
    ) -> list[str]:
        """Fetch candidates from active Sites and Telegram sources, rank joint top_k, and persist.

        Returns:
            list[str]: IDs of the saved top news items.
        """
        # 1. Determine keywords filter (disabled by default)
        if use_db_keywords:
            active_keywords = await self.keyword_repo.get_all_words()
        elif keywords:
            active_keywords = [k.strip() for k in keywords if k.strip()]
        else:
            active_keywords = []

        # 2. Active sources
        site_sources = await self.source_repo.get_active_sources(SourceType.SITE)
        tg_sources = await self.source_repo.get_active_sources(SourceType.TG)

        site_items: list[NewsItemCreate] = []
        if site_sources:
            tasks = [fetch_rss_feed(source.url) for source in site_sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for source, res in zip(site_sources, results):
                if isinstance(res, Exception):
                    logger.warning("Error fetching RSS feed %s: %s", source.url, res)
                else:
                    site_items.extend(res)

        tg_items: list[NewsItemCreate] = []
        if tg_sources:
            async def _fetch_tg_all(tg_c: Any) -> list[Any]:
                tg_tasks = [
                    fetch_channel_posts(
                        tg_c,
                        source.url,
                        limit=limit_per_channel,
                        min_text_length=min_text_length,
                    )
                    for source in tg_sources
                ]
                return await asyncio.gather(*tg_tasks, return_exceptions=True)

            try:
                if client is not None:
                    results = await _fetch_tg_all(client)
                else:
                    async with get_telegram_client() as tg_client:
                        results = await _fetch_tg_all(tg_client)

                for source, res in zip(tg_sources, results):
                    if isinstance(res, Exception):
                        logger.warning("Error fetching TG channel %s: %s", source.url, res)
                    else:
                        tg_items.extend(res)
            except Exception as tg_err:
                logger.error("Error connecting Telegram client in pipeline: %s", tg_err)

        all_items = site_items + tg_items
        if not all_items:
            logger.info("Pipeline found 0 items across all sources.")
            return []

        # 3. Filter by keywords
        relevant_items = filter_relevant_news(all_items, active_keywords)
        if not relevant_items:
            logger.info("None of the %d items matched configured keywords.", len(all_items))
            return []

        # 4. Deduplicate
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

        candidates = [
            item
            for item_id, item in unique_batch_items.items()
            if item_id not in existing_ids and (not item.url or item.url not in existing_urls)
        ]

        # 4.1 Filter candidates by publication freshness (published_at >= cutoff)
        resolved_max_age = max_age_hours if max_age_hours is not None else settings.NEWS_MAX_AGE_HOURS
        if resolved_max_age and resolved_max_age > 0:
            cutoff = datetime.now(UTC) - timedelta(hours=resolved_max_age)

            def _is_fresh(item: NewsItemCreate) -> bool:
                if not item.published_at:
                    return True
                dt = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=UTC)
                return dt >= cutoff

            fresh_candidates = [c for c in candidates if _is_fresh(c)]
            if len(fresh_candidates) < len(candidates):
                logger.info(
                    "Filtered out %d stale candidate articles (published more than %s hours ago).",
                    len(candidates) - len(fresh_candidates),
                    resolved_max_age,
                )
            candidates = fresh_candidates

        resolved_top_k = top_k if top_k is not None else settings.AI_FILTER_TOP_K
        ai_filter_active = settings.AI_FILTER_ENABLED

        # 5. Score and persist ALL fresh candidates in the database
        if candidates:
            if ai_filter_active:
                logger.info("AI scoring %d fresh candidates...", len(candidates))
                await self.ai_ranker.rank_news(candidates, top_k=None, force_eval=True)

            # Populate raw text for site items if needed
            items_to_populate = [c for c in candidates if not c.raw_text]
            if items_to_populate:
                await populate_articles_raw_text(items_to_populate)

            # Save ALL fresh candidates to database
            await self.news_repo.save_news_items(candidates)
            logger.info("Saved %d fresh news items to database with AI evaluations.", len(candidates))
        else:
            logger.info("0 fresh candidates found across sources.")

        # 6. Form selection pool for top-k posts:
        # If fresh candidates < 10, pull up to 10 unposted top news from DB (filtered by freshness)
        pool: list[Any] = list(candidates)

        if len(candidates) < 10:
            fresh_ids = {c.id for c in candidates if c.id}
            needed_from_db = 10
            logger.info(
                "Fresh news count (%d) is less than 10. Pulling up to %d unposted top news from DB...",
                len(candidates),
                needed_from_db,
            )
            db_unposted = await self.news_repo.get_unposted_top_news(
                limit=needed_from_db,
                exclude_ids=fresh_ids,
                max_age_hours=resolved_max_age,
            )
            logger.info("Retrieved %d unposted news items from database.", len(db_unposted))
            pool.extend(db_unposted)

        if not pool:
            logger.info("No candidates available for post generation.")
            return []

        # Sort pool descending by ai_score (and secondary by parsed_at)
        def _candidate_score_key(item: Any) -> tuple[float, float]:
            score = getattr(item, "ai_score", None)
            s_val = float(score) if score is not None else 0.0
            parsed_dt = getattr(item, "parsed_at", None)
            ts_val = parsed_dt.timestamp() if parsed_dt is not None else 0.0
            return (s_val, ts_val)

        pool.sort(key=_candidate_score_key, reverse=True)

        selected_top = pool[:resolved_top_k]
        selected_ids = [item.id for item in selected_top if item.id]
        logger.info(
            "Selected top %d news for post generation: %s",
            len(selected_ids),
            selected_ids,
        )
        return selected_ids


