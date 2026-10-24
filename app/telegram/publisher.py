import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelInvalidError,
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from app.config import settings
from app.models import Post, StatusType
from app.news_parser.exceptions import (
    TelegramParserError,
    TelegramUnauthorizedError,
)
from app.news_parser.telegram import (
    clean_channel_username,
    clean_error_message,
    get_telegram_client,
)
from app.repositories.post_repository import PostRepository
from app.telegram.exceptions import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    TelegramChannelValidationError,
    TelegramPublishChannelError,
    TelegramPublishError,
    TelegramPublishFloodWaitError,
    TelegramPublishForbiddenError,
    TelegramPublishUnauthorizedError,
)

logger = logging.getLogger(__name__)


def normalize_target_channel(channel: str | int | None) -> str | int | None:
    """Normalize target channel identifier into either an integer ID or clean username."""
    if channel is None:
        return None
    if isinstance(channel, int):
        return channel

    cleaned = str(channel).strip()
    if not cleaned:
        return None

    # Support numeric channel IDs like -1001234567890 or 123456789
    if (cleaned.startswith("-") and cleaned[1:].isdigit()) or cleaned.isdigit():
        try:
            return int(cleaned)
        except ValueError:
            pass

    # Extract username if given as full t.me link
    if "t.me/" in cleaned:

        try:
            username = clean_channel_username(cleaned)
            if username:
                return f"@{username}"
        except Exception:
            pass

    return cleaned


class TelegramPublisher:
    """Service for publishing AI-generated posts to Telegram channels via Telethon."""

    def __init__(
        self,
        session: AsyncSession,
        client: Any = None,
        post_repo: PostRepository | None = None,
    ):
        self.session = session
        self.client = client
        self.post_repo = post_repo or PostRepository(session)

    async def _mark_failed(self, post_id: int) -> None:
        """Helper to safely record FAILED status on a post in the database."""
        try:
            await self.post_repo.update_status(
                post_id=post_id,
                status=StatusType.FAILED,
            )
        except Exception as db_err:
            logger.error("Failed to update post %s status to FAILED: %s", post_id, db_err)

    async def publish_post(
        self,
        post_id: int,
        target_channel: str | int | None = None,
    ) -> Post:
        """Publish a post to the designated Telegram channel.

        Args:
            post_id: Primary key of the post to publish.
            target_channel: Optional target channel override (@username or channel ID).
                            Defaults to settings.TG_TARGET_CHANNEL.

        Returns:
            Updated Post instance with PUBLISHED status and timestamp.

        Raises:
            PostNotFoundError: If post_id does not exist in the database.
            PostAlreadyPublishedError: If post is already in PUBLISHED status (deduplication).
            TelegramChannelValidationError: If target channel is not specified or configured.
            TelegramPublishForbiddenError: If lacking permissions to post in the channel.
            TelegramPublishChannelError: If channel is private, invalid, or does not exist.
            TelegramPublishFloodWaitError: If Telegram rate limit / flood wait is triggered.
            TelegramPublishUnauthorizedError: If Telegram session is not authorized.
            TelegramPublishError: For any other sending or network failures.
        """
        # 1. Retrieve post from database
        post = await self.post_repo.get_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post with id {post_id} not found")

        # 2. Validation & Deduplication: block if already published
        if post.status == StatusType.PUBLISHED:
            raise PostAlreadyPublishedError(
                f"Post {post_id} has already been published at {post.published_at}. Duplicate publishing blocked."
            )

        # 3. Determine target channel (argument override or configuration fallback)
        normalized_channel = normalize_target_channel(target_channel) or normalize_target_channel(settings.TG_TARGET_CHANNEL)
        if not normalized_channel:
            raise TelegramChannelValidationError(
                "Target channel is not specified in request and TG_TARGET_CHANNEL is not configured in settings."
            )

        # Validate that post content is not empty
        if not post.generated_text or not post.generated_text.strip():
            logger.warning("Post %s has empty generated_text; cannot publish.", post_id)
            await self._mark_failed(post_id)
            raise TelegramPublishError(f"Post {post_id} has empty generated_text; cannot publish.")

        # 4. Publish via Telethon client
        try:
            async with get_telegram_client(self.client) as tg_client:
                await tg_client.send_message(
                    normalized_channel,
                    post.generated_text,
                    parse_mode="md",
                )
        except ChatWriteForbiddenError as e:
            logger.error("Forbidden to write to channel '%s' for post %s: %s", normalized_channel, post_id, e)
            await self._mark_failed(post_id)
            raise TelegramPublishForbiddenError(
                f"Cannot publish to channel '{normalized_channel}': write permission forbidden or bot/user is not admin: {clean_error_message(e)}"
            ) from e
        except (
            ChannelPrivateError,
            ChannelInvalidError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
        ) as e:
            logger.error("Channel '%s' invalid or private for post %s: %s", normalized_channel, post_id, e)
            await self._mark_failed(post_id)
            raise TelegramPublishChannelError(
                f"Channel '{normalized_channel}' not found, private, or inaccessible: {clean_error_message(e)}"
            ) from e
        except FloodWaitError as e:
            logger.error("Flood wait of %s seconds while publishing post %s to '%s'", e.seconds, post_id, normalized_channel)
            await self._mark_failed(post_id)
            raise TelegramPublishFloodWaitError(
                f"Telegram rate limit: flood wait {e.seconds}s",
                seconds=e.seconds,
            ) from e
        except (TelegramUnauthorizedError, AuthKeyUnregisteredError) as e:
            logger.error("Telegram session not authorized while publishing post %s: %s", post_id, e)
            await self._mark_failed(post_id)
            raise TelegramPublishUnauthorizedError(
                f"Telegram session is not authorized: {clean_error_message(e)}"
            ) from e
        except (RPCError, TelegramParserError) as e:
            logger.error("Telegram RPC error while publishing post %s to '%s': %s", post_id, normalized_channel, e)
            await self._mark_failed(post_id)
            raise TelegramPublishError(
                f"Telegram error publishing to '{normalized_channel}': {clean_error_message(e)}"
            ) from e
        except (ConnectionError, OSError) as e:
            logger.error("Network error while publishing post %s to '%s': %s", post_id, normalized_channel, e)
            await self._mark_failed(post_id)
            raise TelegramPublishError(
                f"Network error while connecting to Telegram: {e}"
            ) from e
        except Exception as e:
            logger.error("Unexpected error publishing post %s to '%s': %s", post_id, normalized_channel, e)
            await self._mark_failed(post_id)
            raise TelegramPublishError(
                f"Failed to publish post {post_id} to '{normalized_channel}': {e}"
            ) from e

        # 5. Success: update post status in DB to PUBLISHED with current UTC timestamp
        now = datetime.now(UTC)
        updated_post = await self.post_repo.update_status(
            post_id=post.id,
            status=StatusType.PUBLISHED,
            published_at=now,
        )
        logger.info("Successfully published post %s to channel '%s' at %s", post_id, normalized_channel, now)
        return updated_post
