from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.exceptions import AIRateLimitError
from app.api.schemas import NewsItemCreate
from app.repositories.news_repository import NewsRepository


@pytest.mark.asyncio
async def test_generate_post_from_custom(client: AsyncClient):
    with patch(
        "app.api.endpoints.PostGenerator.generate_post",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = "🔥 **AI Новина**\n\nОпис новини.\n\n#tech"

        response = await client.post(
            "/api/generate/custom",
            json={
                "title": "Новий чіп",
                "content": "Випущено новий чіп із низьким енергоспоживанням.",
                "source_url": "https://example.com/chip",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["generated_text"] == "🔥 **AI Новина**\n\nОпис новини.\n\n#tech"


@pytest.mark.asyncio
async def test_generate_post_from_custom_validation_error(client: AsyncClient):
    response = await client.post(
        "/api/generate/custom",
        json={},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_post_from_custom_rate_limit_error(client: AsyncClient):
    with patch(
        "app.api.endpoints.PostGenerator.generate_post",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.side_effect = AIRateLimitError("429 Quota Exceeded")

        response = await client.post(
            "/api/generate/custom",
            json={"title": "Заголовок", "content": "Опис"},
        )
        assert response.status_code == 429
        assert "Rate limit" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_post_from_news_success(
    client: AsyncClient,
    db_session: AsyncSession,
):
    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(
            id="news-gen-1",
            title="Заголовок з БД",
            summary="Опис новини з БД",
            source="https://source.com",
            raw_text="Повний текст новини для генерації.",
        )
    ])

    with patch(
        "app.api.endpoints.PostGenerator.generate_post",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = "🚀 **Пост на основі новини**\n\nДеталі.\n\n#ua"

        response = await client.post(
            "/api/generate/news",
            json={"news_id": "news-gen-1"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["news_id"] == "news-gen-1"
        assert data["id"] is not None
        assert data["status"] == "generated"
        assert "🚀 **Пост на основі новини**" in data["generated_text"]

        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["summary"] == "Опис новини з БД"
        assert call_kwargs["raw_text"] == "Повний текст новини для генерації."

        # Verify saved in posts list
        posts_response = await client.get("/api/posts")
        assert posts_response.status_code == 200
        posts = posts_response.json()
        assert len(posts) == 1
        assert posts[0]["id"] == data["id"]
        assert posts[0]["news_id"] == "news-gen-1"


@pytest.mark.asyncio
async def test_generate_post_from_news_not_found(client: AsyncClient):
    response = await client.post(
        "/api/generate/news",
        json={"news_id": "non-existent-id"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_post_from_news_duplicate_and_regenerate(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from app.models import StatusType
    from app.repositories.post_repository import PostRepository

    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(id="news-dup-test", title="Title", summary="Sum", source="src")
    ])

    with patch(
        "app.api.endpoints.PostGenerator.generate_post",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = "Перша версія поста"

        # 1. First generation succeeds
        res1 = await client.post("/api/generate/news", json={"news_id": "news-dup-test"})
        assert res1.status_code == 201
        post_id = res1.json()["id"]

        # 2. Duplicate generation without regenerate=True returns 409 Conflict
        res2 = await client.post("/api/generate/news", json={"news_id": "news-dup-test"})
        assert res2.status_code == 409
        assert "already exists" in res2.json()["detail"]

        # 3. Generation with regenerate=True updates the existing post
        mock_gen.return_value = "Оновлена версія поста"
        res3 = await client.post(
            "/api/generate/news",
            json={"news_id": "news-dup-test", "regenerate": True},
        )
        assert res3.status_code == 201 or res3.status_code == 200
        assert res3.json()["id"] == post_id
        assert res3.json()["generated_text"] == "Оновлена версія поста"

        # 4. If post is already PUBLISHED, regeneration is forbidden (409 Conflict)
        await post_repo.update_status(post_id, StatusType.PUBLISHED)
        res4 = await client.post(
            "/api/generate/news",
            json={"news_id": "news-dup-test", "regenerate": True},
        )
        assert res4.status_code == 409
        assert "already been published" in res4.json()["detail"]



@pytest.mark.asyncio
async def test_get_posts_and_get_post_by_id(
    client: AsyncClient,
    db_session: AsyncSession,
):
    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(
            id="item-posts-check",
            title="Заголовок",
            summary="Опис",
            source="src",
        )
    ])

    with patch(
        "app.api.endpoints.PostGenerator.generate_post",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = "Текст 1"
        res1 = await client.post("/api/generate/news", json={"news_id": "item-posts-check"})
        post_id = res1.json()["id"]

        # Get by id
        get_res = await client.get(f"/api/posts/{post_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == post_id
        assert get_res.json()["generated_text"] == "Текст 1"

        # Not found by id
        not_found_res = await client.get("/api/posts/999999")
        assert not_found_res.status_code == 404


@pytest.mark.asyncio
async def test_publish_post_endpoint_success(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from datetime import UTC, datetime

    from app.models import Post, StatusType
    from app.repositories.post_repository import PostRepository

    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(id="news-publish-1", title="Title", summary="Summary", source="src")
    ])
    post_repo = PostRepository(db_session)
    post = await post_repo.create_post(
        news_id="news-publish-1",
        generated_text="🔥 Generated AI Post text",
        status=StatusType.GENERATED,
    )

    published_time = datetime.now(UTC)
    fake_published_post = Post(
        id=post.id,
        news_id=post.news_id,
        generated_text=post.generated_text,
        status=StatusType.PUBLISHED,
        published_at=published_time,
    )

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.return_value = fake_published_post

        response = await client.post(
            f"/api/posts/{post.id}/publish",
            json={"target_channel": "@my_channel"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == post.id
        assert data["status"] == "published"
        assert data["published_at"] is not None
        mock_publish.assert_awaited_once_with(post_id=post.id, target_channel="@my_channel")


@pytest.mark.asyncio
async def test_publish_post_endpoint_no_body(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from datetime import UTC, datetime

    from app.models import Post, StatusType
    from app.repositories.post_repository import PostRepository

    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(id="news-publish-2", title="Title", summary="Summary", source="src")
    ])
    post_repo = PostRepository(db_session)
    post = await post_repo.create_post(
        news_id="news-publish-2",
        generated_text="🔥 Generated AI Post text",
        status=StatusType.GENERATED,
    )

    fake_published_post = Post(
        id=post.id,
        news_id=post.news_id,
        generated_text=post.generated_text,
        status=StatusType.PUBLISHED,
        published_at=datetime.now(UTC),
    )

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.return_value = fake_published_post

        # Request without any JSON body
        response = await client.post(f"/api/posts/{post.id}/publish")

        assert response.status_code == 200
        assert response.json()["status"] == "published"
        mock_publish.assert_awaited_once_with(post_id=post.id, target_channel=None)


@pytest.mark.asyncio
async def test_publish_post_endpoint_empty_channel_string_uses_default(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from datetime import UTC, datetime
    from app.models import Post, StatusType
    from app.repositories.post_repository import PostRepository

    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(id="news-publish-3", title="Title", summary="Summary", source="src")
    ])
    post_repo = PostRepository(db_session)
    post = await post_repo.create_post(
        news_id="news-publish-3",
        generated_text="🔥 Generated AI Post text",
        status=StatusType.GENERATED,
    )

    fake_published_post = Post(
        id=post.id,
        news_id=post.news_id,
        generated_text=post.generated_text,
        status=StatusType.PUBLISHED,
        published_at=datetime.now(UTC),
    )

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.return_value = fake_published_post

        # Request with empty string {"target_channel": ""} (as from Swagger UI)
        response = await client.post(
            f"/api/posts/{post.id}/publish",
            json={"target_channel": ""},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "published"
        # Schema validator cleans "" to None so publisher falls back to settings.TG_TARGET_CHANNEL
        mock_publish.assert_awaited_once_with(post_id=post.id, target_channel=None)


@pytest.mark.asyncio
async def test_publish_post_endpoint_not_found(client: AsyncClient):
    from app.telegram.exceptions import PostNotFoundError

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.side_effect = PostNotFoundError("Post with id 999 not found")

        response = await client.post(
            "/api/posts/999/publish",
            json={"target_channel": "@channel"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_post_endpoint_conflict_already_published(client: AsyncClient):
    from app.telegram.exceptions import PostAlreadyPublishedError

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.side_effect = PostAlreadyPublishedError("Post 1 has already been published. Duplicate publishing blocked.")

        response = await client.post(
            "/api/posts/1/publish",
            json={"target_channel": "@channel"},
        )

        assert response.status_code == 409
        assert "already been published" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_post_endpoint_bad_request_missing_channel(client: AsyncClient):
    from app.telegram.exceptions import TelegramChannelValidationError

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.side_effect = TelegramChannelValidationError("Target channel is not specified in request and TG_TARGET_CHANNEL is not configured.")

        response = await client.post("/api/posts/1/publish")

        assert response.status_code == 400
        assert "target channel" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_post_endpoint_forbidden(client: AsyncClient):
    from app.telegram.exceptions import TelegramPublishForbiddenError

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.side_effect = TelegramPublishForbiddenError("Cannot publish to channel: write permission forbidden")

        response = await client.post(
            "/api/posts/1/publish",
            json={"target_channel": "@forbidden"},
        )

        assert response.status_code == 403
        assert "permission forbidden" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_post_endpoint_flood_wait(client: AsyncClient):
    from app.telegram.exceptions import TelegramPublishFloodWaitError

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        mock_publish.side_effect = TelegramPublishFloodWaitError("Telegram rate limit: flood wait 30s", seconds=30)

        response = await client.post(
            "/api/posts/1/publish",
            json={"target_channel": "@channel"},
        )

        assert response.status_code == 429
        assert "flood wait" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_post_endpoint_bad_gateway_on_telegram_errors(client: AsyncClient):
    from app.telegram.exceptions import (
        TelegramPublishChannelError,
        TelegramPublishUnauthorizedError,
    )

    with patch(
        "app.api.endpoints.TelegramPublisher.publish_post",
        new_callable=AsyncMock,
    ) as mock_publish:
        # Channel error -> 502
        mock_publish.side_effect = TelegramPublishChannelError("Channel '@invalid' not found or private")
        response1 = await client.post("/api/posts/1/publish", json={"target_channel": "@invalid"})
        assert response1.status_code == 502

        # Unauthorized error -> 502
        mock_publish.side_effect = TelegramPublishUnauthorizedError("Telegram session is not authorized")
        response2 = await client.post("/api/posts/1/publish", json={"target_channel": "@channel"})
        assert response2.status_code == 502


@pytest.mark.asyncio
async def test_publish_post_endpoint_e2e_flow(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """End-to-end test of publish endpoint exercising full TelegramPublisher + DB flow."""
    from contextlib import asynccontextmanager

    from app.models import StatusType
    from app.repositories.post_repository import PostRepository

    news_repo = NewsRepository(db_session)
    await news_repo.save_news_items([
        NewsItemCreate(id="news-publish-e2e", title="E2E Title", summary="E2E Summary", source="src")
    ])
    post_repo = PostRepository(db_session)
    post = await post_repo.create_post(
        news_id="news-publish-e2e",
        generated_text="🚀 **E2E Generated Text**\n\nFull description.",
        status=StatusType.GENERATED,
    )

    mock_tg = AsyncMock()

    @asynccontextmanager
    async def mock_get_telegram_client(*args, **kwargs):
        yield mock_tg

    with patch("app.telegram.publisher.get_telegram_client", mock_get_telegram_client):
        response = await client.post(
            f"/api/posts/{post.id}/publish",
            json={"target_channel": "@e2e_news_channel"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == post.id
        assert data["status"] == "published"
        assert data["published_at"] is not None

        mock_tg.send_message.assert_awaited_once_with(
            "@e2e_news_channel",
            "🚀 **E2E Generated Text**\n\nFull description.",
            parse_mode="md",
        )

        # Check DB state
        db_post = await post_repo.get_by_id(post.id)
        assert db_post.status == StatusType.PUBLISHED
        assert db_post.published_at is not None

        # Verify duplicate publishing via endpoint is now rejected with 409 Conflict
        dup_res = await client.post(
            f"/api/posts/{post.id}/publish",
            json={"target_channel": "@e2e_news_channel"},
        )
        assert dup_res.status_code == 409
        assert "duplicate publishing blocked" in dup_res.json()["detail"].lower()


