from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
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

from app.api.schemas import NewsItemCreate
from app.models import StatusType
from app.news_parser.exceptions import TelegramUnauthorizedError
from app.repositories.news_repository import NewsRepository
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
from app.telegram.publisher import TelegramPublisher, normalize_target_channel


def test_normalize_target_channel():
    assert normalize_target_channel(None) is None
    assert normalize_target_channel("") is None
    assert normalize_target_channel("   ") is None
    assert normalize_target_channel("@my_channel") == "@my_channel"
    assert normalize_target_channel("my_channel") == "my_channel"
    assert normalize_target_channel(-1001234567890) == -1001234567890
    assert normalize_target_channel("-1001234567890") == -1001234567890
    assert normalize_target_channel("123456789") == 123456789
    assert normalize_target_channel("https://t.me/tech_news") == "@tech_news"
    assert normalize_target_channel("t.me/tech_news") == "@tech_news"


async def _create_test_post(db_session: AsyncSession, news_id: str = "news-1", text: str = "AI post content"):
    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(
            id=news_id,
            title="News Title",
            summary="News Summary",
            source="source.com",
            raw_text="Full news text",
        )
    ])
    post_repo = PostRepository(db_session)
    return await post_repo.create_post(
        news_id=news_id,
        generated_text=text,
        status=StatusType.GENERATED,
    )


@pytest.mark.asyncio
async def test_publish_post_success(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-success-1", text="🔥 **Hot AI News**\n\nDetails...")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    published_post = await publisher.publish_post(post.id, target_channel="@target_news")

    # Verify Telethon send_message call
    mock_client.send_message.assert_awaited_once_with(
        "@target_news",
        "🔥 **Hot AI News**\n\nDetails...",
        parse_mode="md",
    )

    # Verify returned post state
    assert published_post.id == post.id
    assert published_post.status == StatusType.PUBLISHED
    assert published_post.published_at is not None
    assert isinstance(published_post.published_at, datetime)

    # Verify persisted in database
    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed is not None
    assert refreshed.status == StatusType.PUBLISHED
    assert refreshed.published_at is not None


@pytest.mark.asyncio
async def test_publish_post_uses_default_target_channel_from_settings(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-settings-fallback")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with patch("app.telegram.publisher.settings.TG_TARGET_CHANNEL", "@fallback_channel"):
        published = await publisher.publish_post(post.id, target_channel=None)

    mock_client.send_message.assert_awaited_once_with(
        "@fallback_channel",
        post.generated_text,
        parse_mode="md",
    )
    assert published.status == StatusType.PUBLISHED


@pytest.mark.asyncio
async def test_publish_post_uses_default_target_channel_when_empty_string(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-empty-channel-fallback")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with patch("app.telegram.publisher.settings.TG_TARGET_CHANNEL", "@fallback_channel"):
        published = await publisher.publish_post(post.id, target_channel="")

    mock_client.send_message.assert_awaited_once_with(
        "@fallback_channel",
        post.generated_text,
        parse_mode="md",
    )
    assert published.status == StatusType.PUBLISHED


@pytest.mark.asyncio
async def test_publish_post_numeric_channel_id(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-numeric-id")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    await publisher.publish_post(post.id, target_channel="-1009876543210")

    mock_client.send_message.assert_awaited_once_with(
        -1009876543210,
        post.generated_text,
        parse_mode="md",
    )


@pytest.mark.asyncio
async def test_publish_post_not_found(db_session: AsyncSession):
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(PostNotFoundError, match="Post with id 99999 not found"):
        await publisher.publish_post(99999, target_channel="@chan")

    mock_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_post_already_published_blocks_duplicate(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-already-published")
    post_repo = PostRepository(db_session)
    await post_repo.update_status(post.id, StatusType.PUBLISHED)

    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(PostAlreadyPublishedError, match="Duplicate publishing blocked"):
        await publisher.publish_post(post.id, target_channel="@target")

    mock_client.send_message.assert_not_awaited()
    # Status should remain PUBLISHED, not modified or failed
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.PUBLISHED


@pytest.mark.asyncio
async def test_publish_post_missing_target_channel(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-missing-channel")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with patch("app.telegram.publisher.settings.TG_TARGET_CHANNEL", None):
        with pytest.raises(TelegramChannelValidationError, match="Target channel is not specified"):
            await publisher.publish_post(post.id, target_channel=None)

    mock_client.send_message.assert_not_awaited()
    # Status should remain GENERATED (not failed)
    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.GENERATED


@pytest.mark.asyncio
async def test_publish_post_empty_generated_text_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-empty-text", text="   ")
    mock_client = AsyncMock()
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishError, match="empty generated_text"):
        await publisher.publish_post(post.id, target_channel="@channel")

    mock_client.send_message.assert_not_awaited()
    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_chat_write_forbidden_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-forbidden")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = ChatWriteForbiddenError(request=None)
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishForbiddenError, match="write permission forbidden"):
        await publisher.publish_post(post.id, target_channel="@forbidden_channel")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_channel_private_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-channel-private")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = ChannelPrivateError(request=None)
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishChannelError, match="inaccessible"):
        await publisher.publish_post(post.id, target_channel="@private_chan")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_channel_invalid_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-channel-invalid")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = ChannelInvalidError(request=None)
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishChannelError):
        await publisher.publish_post(post.id, target_channel="@invalid_chan")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_username_not_occupied_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-username-missing")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = UsernameNotOccupiedError(request=None)
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishChannelError):
        await publisher.publish_post(post.id, target_channel="@no_such_chan")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_flood_wait_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-flood-wait")
    mock_client = AsyncMock()
    flood_err = FloodWaitError(request=None, capture=120)
    mock_client.send_message.side_effect = flood_err
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishFloodWaitError) as exc_info:
        await publisher.publish_post(post.id, target_channel="@channel")

    assert exc_info.value.seconds == 120
    assert "flood wait 120s" in str(exc_info.value)

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_unauthorized_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-unauth")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = TelegramUnauthorizedError("Session expired")
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishUnauthorizedError, match="not authorized"):
        await publisher.publish_post(post.id, target_channel="@channel")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_auth_key_unregistered_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-auth-key-unregistered")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = AuthKeyUnregisteredError(request=None)
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishUnauthorizedError):
        await publisher.publish_post(post.id, target_channel="@channel")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_generic_rpc_error_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-rpc-err")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = RPCError(request=None, message="Internal server error")
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishError, match="Internal server error"):
        await publisher.publish_post(post.id, target_channel="@channel")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED


@pytest.mark.asyncio
async def test_publish_post_network_connection_error_marks_failed(db_session: AsyncSession):
    post = await _create_test_post(db_session, news_id="pub-net-err")
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = ConnectionError("Connection reset by peer")
    publisher = TelegramPublisher(session=db_session, client=mock_client)

    with pytest.raises(TelegramPublishError, match="Network error"):
        await publisher.publish_post(post.id, target_channel="@channel")

    post_repo = PostRepository(db_session)
    refreshed = await post_repo.get_by_id(post.id)
    assert refreshed.status == StatusType.FAILED
