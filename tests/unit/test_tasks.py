from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.schemas import NewsItemCreate
from app.models import NewsItem, Post, Source, SourceType, StatusType
from app.services.news_service import NewsService
from app.tasks import (
    fetch_and_rank_news_task,
    generate_ai_posts_task,
    publish_post_task,
    run_news_pipeline_task,
    schedule_posts_publication_task,
)
from app.telegram.exceptions import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    PostPublishingInProgressError,
    TelegramPublishChannelError,
    TelegramPublishFloodWaitError,
    TelegramPublishForbiddenError,
)
from app.utils import run_async


class TestFetchAndRankNewsTask:
    def test_fetch_and_rank_news_task_success(self):
        mock_service = MagicMock()
        mock_service.fetch_and_rank_pipeline_news = AsyncMock(return_value=["news-1", "news-2"])

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsService", return_value=mock_service),
        ):
            result = fetch_and_rank_news_task(top_k=2)

        assert result == ["news-1", "news-2"]
        mock_service.fetch_and_rank_pipeline_news.assert_awaited_once_with(
            top_k=2, use_db_keywords=False
        )

    def test_fetch_and_rank_news_task_empty(self):
        mock_service = MagicMock()
        mock_service.fetch_and_rank_pipeline_news = AsyncMock(return_value=[])

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsService", return_value=mock_service),
        ):
            result = fetch_and_rank_news_task()

        assert result == []
        mock_service.fetch_and_rank_pipeline_news.assert_awaited_once_with(
            top_k=None, use_db_keywords=False
        )


class TestGenerateAIPostsTask:
    def test_generate_ai_posts_task_empty_input(self):
        result = generate_ai_posts_task([])
        assert result == []

    def test_generate_ai_posts_task_success(self):
        mock_news = NewsItem(
            id="n1",
            title="Title 1",
            summary="Summary 1",
            raw_text="Raw 1",
            url="https://ex.com/1",
            source="source.com",
        )
        mock_post = Post(id=101, news_id="n1", generated_text="AI Post 1", status=StatusType.GENERATED)

        mock_news_repo = MagicMock()
        mock_news_repo.get_by_id = AsyncMock(return_value=mock_news)

        mock_post_repo = MagicMock()
        mock_post_repo.get_by_news_id = AsyncMock(return_value=None)
        mock_post_repo.create_post = AsyncMock(return_value=mock_post)

        mock_generator = MagicMock()
        mock_generator.generate_post = AsyncMock(return_value="AI Post 1")

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsRepository", return_value=mock_news_repo),
            patch("app.tasks.PostRepository", return_value=mock_post_repo),
            patch("app.tasks.PostGenerator", return_value=mock_generator),
        ):
            result = generate_ai_posts_task(["n1"])

        assert result == [101]
        mock_generator.generate_post.assert_awaited_once_with(
            title="Title 1",
            content="Summary 1",
            summary="Summary 1",
            raw_text="Raw 1",
            source_url="https://ex.com/1",
        )
        mock_post_repo.create_post.assert_awaited_once_with(
            news_id="n1",
            generated_text="AI Post 1",
            status=StatusType.GENERATED,
        )

    def test_generate_ai_posts_task_reuses_existing_post(self):
        existing_post = Post(id=88, news_id="n1", generated_text="Old Post", status=StatusType.GENERATED)

        mock_post_repo = MagicMock()
        mock_post_repo.get_by_news_id = AsyncMock(return_value=existing_post)
        mock_post_repo.create_post = AsyncMock()

        mock_news_repo = MagicMock()
        mock_generator = MagicMock()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsRepository", return_value=mock_news_repo),
            patch("app.tasks.PostRepository", return_value=mock_post_repo),
            patch("app.tasks.PostGenerator", return_value=mock_generator),
        ):
            result = generate_ai_posts_task(["n1"])

        assert result == [88]
        mock_post_repo.create_post.assert_not_awaited()
        mock_generator.generate_post.assert_not_called()

    def test_generate_ai_posts_task_skips_missing_news(self):
        mock_post_repo = MagicMock()
        mock_post_repo.get_by_news_id = AsyncMock(return_value=None)

        mock_news_repo = MagicMock()
        mock_news_repo.get_by_id = AsyncMock(return_value=None)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsRepository", return_value=mock_news_repo),
            patch("app.tasks.PostRepository", return_value=mock_post_repo),
        ):
            result = generate_ai_posts_task(["missing-news-id"])

        assert result == []

    def test_generate_ai_posts_task_handles_individual_generation_error(self):
        mock_news_1 = NewsItem(id="n1", title="Title 1", summary="Sum 1", source="s1")
        mock_news_2 = NewsItem(id="n2", title="Title 2", summary="Sum 2", source="s2")

        mock_news_repo = MagicMock()
        mock_news_repo.get_by_id = AsyncMock(side_effect=[mock_news_1, mock_news_2])

        mock_post = Post(id=102, news_id="n2", generated_text="AI Post 2", status=StatusType.GENERATED)
        mock_post_repo = MagicMock()
        mock_post_repo.get_by_news_id = AsyncMock(return_value=None)
        mock_post_repo.create_post = AsyncMock(return_value=mock_post)

        mock_generator = MagicMock()
        mock_generator.generate_post = AsyncMock(
            side_effect=[RuntimeError("OpenAI API Down"), "AI Post 2"]
        )

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.NewsRepository", return_value=mock_news_repo),
            patch("app.tasks.PostRepository", return_value=mock_post_repo),
            patch("app.tasks.PostGenerator", return_value=mock_generator),
        ):
            result = generate_ai_posts_task(["n1", "n2"])

        # n1 failed, n2 succeeded
        assert result == [102]


class TestSchedulePostsPublicationTask:
    def test_schedule_empty(self):
        result = schedule_posts_publication_task([])
        assert result == []

    def test_schedule_three_posts_with_intervals(self):
        with patch("app.tasks.publish_post_task.apply_async") as mock_apply:
            result = schedule_posts_publication_task([101, 102, 103])

        assert result == [101, 102, 103]
        assert mock_apply.call_count == 3
        mock_apply.assert_any_call(args=[101], countdown=0)
        mock_apply.assert_any_call(args=[102], countdown=600)
        mock_apply.assert_any_call(args=[103], countdown=1200)


class TestRunNewsPipelineTask:
    def test_run_news_pipeline_chains_workflow(self):
        mock_chain = MagicMock()
        mock_async_result = MagicMock()
        mock_chain.apply_async.return_value = mock_async_result

        with patch("app.tasks.chain", return_value=mock_chain) as mock_chain_builder:
            res = run_news_pipeline_task()

        mock_chain_builder.assert_called_once()
        mock_chain.apply_async.assert_called_once()
        assert res == mock_async_result


class TestPublishPostTask:
    def test_publish_post_task_success(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
        ):
            result = publish_post_task(post_id=42)

        assert result == {"post_id": 42, "status": "published"}
        mock_publisher.publish_post.assert_awaited_once_with(42)

    def test_publish_post_task_flood_wait_retries(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(
            side_effect=TelegramPublishFloodWaitError("Rate limited", seconds=30)
        )

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_retry = MagicMock(side_effect=RuntimeError("Retried"))

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
            patch.object(publish_post_task, "retry", mock_retry),
        ):
            with pytest.raises(RuntimeError, match="Retried"):
                publish_post_task(post_id=42)

            mock_retry.assert_called_once()
            _, kwargs = mock_retry.call_args
            assert kwargs["countdown"] == 30

    def test_publish_post_task_network_error_retries(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(side_effect=ConnectionError("Telegram connection lost"))

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_retry = MagicMock(side_effect=RuntimeError("Retried"))

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
            patch.object(publish_post_task, "retry", mock_retry),
        ):
            with pytest.raises(RuntimeError, match="Retried"):
                publish_post_task(post_id=42)

            mock_retry.assert_called_once()
            _, kwargs = mock_retry.call_args
            assert kwargs["countdown"] == 60  # 60 * (2 ** 0)

    def test_publish_post_task_already_published_skipped(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(
            side_effect=PostAlreadyPublishedError("Post 42 already published")
        )

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
        ):
            result = publish_post_task(post_id=42)

        assert result["status"] == "skipped"
        assert result["post_id"] == 42
        assert "already published" in result["reason"]

    def test_publish_post_task_publishing_in_progress_skipped(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(
            side_effect=PostPublishingInProgressError("Post 42 is currently publishing")
        )

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
        ):
            result = publish_post_task(post_id=42)

        assert result["status"] == "skipped"
        assert result["post_id"] == 42
        assert "currently publishing" in result["reason"]

    def test_publish_post_task_fatal_error_not_retried(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(
            side_effect=TelegramPublishForbiddenError("403 Forbidden")
        )

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_retry = MagicMock()

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
            patch.object(publish_post_task, "retry", mock_retry),
        ):
            with pytest.raises(TelegramPublishForbiddenError):
                publish_post_task(post_id=42)

            mock_retry.assert_not_called()

    def test_publish_post_task_post_not_found_not_retried(self):
        mock_publisher = MagicMock()
        mock_publisher.publish_post = AsyncMock(side_effect=PostNotFoundError("Post 42 not found"))

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_retry = MagicMock()

        with (
            patch("app.tasks.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.tasks.TelegramPublisher", return_value=mock_publisher),
            patch.object(publish_post_task, "retry", mock_retry),
        ):
            with pytest.raises(PostNotFoundError):
                publish_post_task(post_id=42)

            mock_retry.assert_not_called()


class TestUtilsAndService:
    def test_run_async_executes_coroutine(self):
        async def sample():
            return 12345

        res = run_async(sample())
        assert res == 12345

    @pytest.mark.asyncio
    async def test_fetch_and_rank_pipeline_news_service(self):
        mock_session = AsyncMock()
        service = NewsService(mock_session)

        fake_site = Source(id=1, name="Site", url="https://site.com/rss", type=SourceType.SITE, enabled=True)
        fake_tg = Source(id=2, name="TG", url="@channel", type=SourceType.TG, enabled=True)

        service.source_repo.get_active_sources = AsyncMock(side_effect=[[fake_site], [fake_tg]])
        service.keyword_repo.get_all_words = AsyncMock(return_value=["новина"])

        item1 = NewsItemCreate(id="id1", title="Тестова новина 1", summary="Деталі 1", url="https://site.com/1", source="site")
        item2 = NewsItemCreate(id="id2", title="Тестова новина 2", summary="Деталі 2", url="https://site.com/2", source="tg", raw_text="TG text")

        saved_item1 = NewsItem(id="id1", title=item1.title, summary=item1.summary, url=item1.url, source=item1.source)
        saved_item2 = NewsItem(id="id2", title=item2.title, summary=item2.summary, url=item2.url, source=item2.source)

        service.news_repo.get_existing_ids = AsyncMock(return_value=set())
        service.news_repo.get_existing_urls = AsyncMock(return_value=set())
        service.news_repo.save_news_items = AsyncMock(return_value=[saved_item1, saved_item2])
        service.news_repo.get_unposted_top_news = AsyncMock(return_value=[])

        with (
            patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item1])),
            patch("app.services.news_service.fetch_channel_posts", new=AsyncMock(return_value=[item2])),
            patch("app.services.news_service.get_telegram_client") as mock_tg_client_ctx,
            patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
            patch.object(service.ai_ranker, "rank_news", new=AsyncMock(return_value=[item1, item2])),
        ):
            mock_tg_client_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_tg_client_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            res = await service.fetch_and_rank_pipeline_news(top_k=2)

        assert set(res) == {"id1", "id2"}
        service.keyword_repo.get_all_words.assert_not_called()
        service.news_repo.save_news_items.assert_awaited_once_with([item1, item2])
        service.news_repo.get_unposted_top_news.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_and_rank_pipeline_news_supplements_from_db(self):
        mock_session = AsyncMock()
        service = NewsService(mock_session)

        # 1 fresh item from site
        fake_site = Source(id=1, name="Site", url="https://site.com/rss", type=SourceType.SITE, enabled=True)
        service.source_repo.get_active_sources = AsyncMock(side_effect=[[fake_site], []])
        service.keyword_repo.get_all_words = AsyncMock(return_value=[])

        fresh_item = NewsItemCreate(id="fresh-1", title="Fresh 1", summary="S1", url="https://site.com/1", source="site", ai_score=6.0)

        # 2 unposted items from DB with higher score
        db_item1 = NewsItem(id="db-1", title="DB 1", summary="D1", url="https://site.com/db1", source="site", ai_score=9.5)
        db_item2 = NewsItem(id="db-2", title="DB 2", summary="D2", url="https://site.com/db2", source="site", ai_score=8.0)

        service.news_repo.get_existing_ids = AsyncMock(return_value=set())
        service.news_repo.get_existing_urls = AsyncMock(return_value=set())
        service.news_repo.save_news_items = AsyncMock(return_value=[fresh_item])
        service.news_repo.get_unposted_top_news = AsyncMock(return_value=[db_item1, db_item2])

        with (
            patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[fresh_item])),
            patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
            patch.object(service.ai_ranker, "rank_news", new=AsyncMock(return_value=[fresh_item])),
        ):
            res = await service.fetch_and_rank_pipeline_news(top_k=2)

        # Top 2 should be db-1 (9.5) and db-2 (8.0), fresh-1 (6.0) is not in top 2
        assert res == ["db-1", "db-2"]
        # But fresh_item was still saved in DB!
        service.news_repo.save_news_items.assert_awaited_once_with([fresh_item])
        service.news_repo.get_unposted_top_news.assert_awaited_once_with(limit=10, exclude_ids={"fresh-1"})
