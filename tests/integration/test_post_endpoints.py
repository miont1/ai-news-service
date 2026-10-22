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
