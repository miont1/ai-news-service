import logging
from typing import Any

from celery import chain

from app.ai.generator import PostGenerator
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import StatusType
from app.repositories.news_repository import NewsRepository
from app.repositories.post_repository import PostRepository
from app.services.news_service import NewsService
from app.telegram.exceptions import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    PostPublishingInProgressError,
    TelegramChannelValidationError,
    TelegramPublishChannelError,
    TelegramPublishFloodWaitError,
    TelegramPublishForbiddenError,
    TelegramPublishNetworkError,
    TelegramPublishUnauthorizedError,
)
from app.telegram.publisher import TelegramPublisher
from app.utils import run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.fetch_and_rank_news_task")
def fetch_and_rank_news_task(
    top_k: int | None = None,
    use_db_keywords: bool = False,
) -> list[str]:
    """Celery task step 1: Collect candidates (RSS + TG), filter, AI-rank top-k, and persist."""
    async def _run() -> list[str]:
        async with AsyncSessionLocal() as session:
            service = NewsService(session)
            return await service.fetch_and_rank_pipeline_news(
                top_k=top_k,
                use_db_keywords=use_db_keywords,
            )

    return run_async(_run())


@celery_app.task(name="app.tasks.generate_ai_posts_task")
def generate_ai_posts_task(news_ids: list[str]) -> list[int]:
    """Celery task step 2: Generate AI posts for selected news items and persist as GENERATED."""
    if not news_ids:
        logger.info("No news IDs provided for post generation; skipping.")
        return []

    async def _run() -> list[int]:
        async with AsyncSessionLocal() as session:
            news_repo = NewsRepository(session)
            post_repo = PostRepository(session)
            generator = PostGenerator()

            created_post_ids: list[int] = []
            for news_id in news_ids:
                existing_post = await post_repo.get_by_news_id(news_id)
                if existing_post:
                    logger.info("Post for news item %s already exists (id=%s).", news_id, existing_post.id)
                    created_post_ids.append(existing_post.id)
                    continue

                news_item = await news_repo.get_by_id(news_id)
                if not news_item:
                    logger.warning("News item %s not found in DB; skipping.", news_id)
                    continue

                try:
                    generated_text = await generator.generate_post(
                        title=news_item.title,
                        content=news_item.summary,
                        summary=news_item.summary,
                        raw_text=news_item.raw_text,
                        source_url=news_item.url,
                    )
                    post = await post_repo.create_post(
                        news_id=news_item.id,
                        generated_text=generated_text,
                        status=StatusType.GENERATED,
                    )
                    created_post_ids.append(post.id)
                    logger.info("Generated post %s for news %s", post.id, news_item.id)
                except Exception as exc:
                    logger.error("Failed to generate post for news %s: %s", news_id, exc)

            return created_post_ids

    return run_async(_run())


@celery_app.task(name="app.tasks.schedule_posts_publication_task")
def schedule_posts_publication_task(post_ids: list[int]) -> list[int]:
    """Celery task step 3: Dispatch deferred publication tasks with 10-minute intervals."""
    if not post_ids:
        logger.info("No post IDs provided to schedule.")
        return []

    scheduled_ids: list[int] = []
    interval_seconds = 600

    for i, post_id in enumerate(post_ids):
        countdown = i * interval_seconds
        publish_post_task.apply_async(args=[post_id], countdown=countdown)
        scheduled_ids.append(post_id)
        logger.info(
            "Scheduled publication for post %s with countdown=%ss (slot %d)",
            post_id,
            countdown,
            i + 1,
        )

    return scheduled_ids


@celery_app.task(name="app.tasks.run_news_pipeline_task")
def run_news_pipeline_task():
    """Celery Beat entrypoint: triggers the 3-step chain for the news pipeline."""
    workflow = chain(
        fetch_and_rank_news_task.s(),
        generate_ai_posts_task.s(),
        schedule_posts_publication_task.s(),
    )
    return workflow.apply_async()


def _mark_post_failed(post_id: int) -> None:
    """Helper to record FAILED status on a post when all Celery publication retries are exhausted."""
    async def _fail() -> None:
        async with AsyncSessionLocal() as session:
            repo = PostRepository(session)
            await repo.update_status(post_id=post_id, status=StatusType.FAILED)

    try:
        run_async(_fail())
    except Exception as exc:
        logger.error("Failed to mark post %s as FAILED: %s", post_id, exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.tasks.publish_post_task",
)
def publish_post_task(self, post_id: int) -> dict[str, Any]:
    """Celery task: Publish an individual post to Telegram via TelegramPublisher.

    Retries with custom countdown on Telegram rate limits (FloodWait) and transient
    network connectivity issues. Permanent failures are logged without retrying.
    Marks post as FAILED only after all retry attempts are exhausted.
    """
    async def _publish() -> None:
        async with AsyncSessionLocal() as session:
            publisher = TelegramPublisher(session)
            await publisher.publish_post(post_id)

    try:
        run_async(_publish())
        logger.info("Successfully completed publish_post_task for post %s", post_id)
        return {"post_id": post_id, "status": "published"}

    except TelegramPublishFloodWaitError as exc:
        countdown = exc.seconds or 60
        if self.request.retries >= self.max_retries:
            logger.error(
                "Max retries (%s) exceeded on FloodWait for post %s. Marking post as FAILED.",
                self.max_retries,
                post_id,
            )
            _mark_post_failed(post_id)
            raise

        logger.warning(
            "FloodWait of %ss encountered for post %s. Retrying in %ss (attempt %s/%s)...",
            exc.seconds,
            post_id,
            countdown,
            self.request.retries + 1,
            self.max_retries,
        )
        raise self.retry(exc=exc, countdown=countdown)

    except (TelegramPublishNetworkError, ConnectionError, OSError) as exc:
        countdown = 60 * (2 ** self.request.retries)
        if self.request.retries >= self.max_retries:
            logger.error(
                "Max retries (%s) exceeded on network failure for post %s: %s. Marking post as FAILED.",
                self.max_retries,
                post_id,
                exc,
            )
            _mark_post_failed(post_id)
            raise

        logger.warning(
            "Network failure publishing post %s: %s. Retrying in %ss (attempt %s/%s)...",
            post_id,
            exc,
            countdown,
            self.request.retries + 1,
            self.max_retries,
        )
        raise self.retry(exc=exc, countdown=countdown)

    except (PostAlreadyPublishedError, PostPublishingInProgressError) as exc:
        logger.warning("Publication skipped for post %s: %s", post_id, exc)
        return {"post_id": post_id, "status": "skipped", "reason": str(exc)}

    except (
        PostNotFoundError,
        TelegramChannelValidationError,
        TelegramPublishForbiddenError,
        TelegramPublishChannelError,
        TelegramPublishUnauthorizedError,
    ) as exc:
        logger.error("Permanent error publishing post %s: %s. Aborting retries.", post_id, exc)
        raise

    except Exception as exc:
        logger.error("Unexpected error publishing post %s: %s", post_id, exc)
        raise
