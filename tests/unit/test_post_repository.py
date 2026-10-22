import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import NewsItemCreate
from app.models import StatusType
from app.repositories.news_repository import NewsRepository
from app.repositories.post_repository import PostRepository


@pytest.mark.asyncio
async def test_create_and_get_post(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    # First create a news item because Post.news_id is a foreign key
    item = NewsItemCreate(
        id="test-news-123",
        title="Тестова новина",
        summary="Тестовий опис",
        source="https://test.com",
    )
    await news_repo.save_news_items([item])

    post = await post_repo.create_post(
        news_id="test-news-123",
        generated_text="🚀 **Згенерований пост**\n\nТекст новини.",
        status=StatusType.GENERATED,
    )

    assert post.id is not None
    assert post.news_id == "test-news-123"
    assert post.status == StatusType.GENERATED
    assert post.published_at is None

    fetched = await post_repo.get_by_id(post.id)
    assert fetched is not None
    assert fetched.generated_text == post.generated_text


@pytest.mark.asyncio
async def test_get_by_news_id(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    item = NewsItemCreate(
        id="test-news-456",
        title="Новина для перевірки news_id",
        summary="Опис",
        source="https://test.com",
    )
    await news_repo.save_news_items([item])

    await post_repo.create_post(
        news_id="test-news-456",
        generated_text="Пост 1",
    )

    fetched = await post_repo.get_by_news_id("test-news-456")
    assert fetched is not None
    assert fetched.generated_text == "Пост 1"

    none_fetched = await post_repo.get_by_news_id("non-existent-id")
    assert none_fetched is None


@pytest.mark.asyncio
async def test_get_posts_with_status_filter(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    item1 = NewsItemCreate(id="n-1", title="Title 1", summary="S1", source="src")
    item2 = NewsItemCreate(id="n-2", title="Title 2", summary="S2", source="src")
    await news_repo.save_news_items([item1, item2])

    p1 = await post_repo.create_post("n-1", "Text 1", status=StatusType.GENERATED)
    p2 = await post_repo.create_post("n-2", "Text 2", status=StatusType.PUBLISHED)

    all_posts = await post_repo.get_posts()
    assert len(all_posts) == 2

    generated_posts = await post_repo.get_posts(status=StatusType.GENERATED)
    assert len(generated_posts) == 1
    assert generated_posts[0].id == p1.id

    published_posts = await post_repo.get_posts(status=StatusType.PUBLISHED)
    assert len(published_posts) == 1
    assert published_posts[0].id == p2.id


@pytest.mark.asyncio
async def test_update_status(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    item = NewsItemCreate(id="n-update", title="Title", summary="S", source="src")
    await news_repo.save_news_items([item])

    post = await post_repo.create_post("n-update", "Text", status=StatusType.GENERATED)
    assert post.published_at is None

    updated = await post_repo.update_status(post.id, status=StatusType.PUBLISHED)
    assert updated is not None
    assert updated.status == StatusType.PUBLISHED
    assert updated.published_at is not None


@pytest.mark.asyncio
async def test_update_generated_text(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    item = NewsItemCreate(id="n-text-upd", title="Title", summary="S", source="src")
    await news_repo.save_news_items([item])

    post = await post_repo.create_post("n-text-upd", "Old text", status=StatusType.GENERATED)
    updated = await post_repo.update_generated_text(post.id, "New generated text")

    assert updated is not None
    assert updated.generated_text == "New generated text"
    assert updated.id == post.id


@pytest.mark.asyncio
async def test_get_posts_filter_by_news_id(db_session: AsyncSession):
    news_repo = NewsRepository(db_session)
    post_repo = PostRepository(db_session)

    item1 = NewsItemCreate(id="news-a", title="A", summary="A", source="src")
    item2 = NewsItemCreate(id="news-b", title="B", summary="B", source="src")
    await news_repo.save_news_items([item1, item2])

    p1 = await post_repo.create_post("news-a", "Post A")
    p2 = await post_repo.create_post("news-b", "Post B")

    results_a = await post_repo.get_posts(news_id="news-a")
    assert len(results_a) == 1
    assert results_a[0].id == p1.id

    results_b = await post_repo.get_posts(news_id="news-b")
    assert len(results_b) == 1
    assert results_b[0].id == p2.id

