from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import NewsItemCreate
from app.models import NewsItem
from app.repositories.news_repository import NewsRepository


@pytest.mark.asyncio
async def test_save_news_items_batch_success(db_session: AsyncSession):
    repo = NewsRepository(db_session)
    item1 = NewsItemCreate(title="News 1", summary="S1", url="https://ex.com/1", source="src", published_at=datetime.now(UTC))
    item2 = NewsItemCreate(title="News 2", summary="S2", url="https://ex.com/2", source="src", published_at=datetime.now(UTC))

    saved = await repo.save_news_items([item1, item2])
    assert len(saved) == 2

    # Verify present in DB
    result = await db_session.execute(select(NewsItem))
    items = result.scalars().all()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_save_news_items_fallback_on_integrity_error(db_session: AsyncSession):
    repo = NewsRepository(db_session)

    # 1. First, save an item in DB
    existing_item = NewsItemCreate(
        title="Existing News",
        summary="Already in DB",
        url="https://ex.com/already-exists",
        source="src",
        published_at=datetime.now(UTC),
    )
    await repo.save_news_items([existing_item])

    # 2. Prepare a batch containing the existing item AND a brand new item
    new_item = NewsItemCreate(
        title="Brand New News",
        summary="Not yet in DB",
        url="https://ex.com/brand-new",
        source="src",
        published_at=datetime.now(UTC),
    )

    # 3. Calling save_news_items on both: batch commit will fail on existing_item's primary key (IntegrityError),
    # triggering the fallback that commits valid items individually.
    saved = await repo.save_news_items([existing_item, new_item])

    # 4. Verify fallback saved only the new item
    assert len(saved) == 1
    assert saved[0].id == new_item.id

    # Verify total in DB is now 2
    result = await db_session.execute(select(NewsItem))
    all_db_items = result.scalars().all()
    assert len(all_db_items) == 2
    assert {i.id for i in all_db_items} == {existing_item.id, new_item.id}


@pytest.mark.asyncio
async def test_get_existing_ids_empty_and_populated(db_session: AsyncSession):
    repo = NewsRepository(db_session)

    # Empty check
    assert await repo.get_existing_ids([]) == set()

    # Save one item
    item = NewsItemCreate(title="Item", summary="S", url="https://ex.com", source="src")
    await repo.save_news_items([item])

    # Query with item.id and another random id
    existing = await repo.get_existing_ids([item.id, "random-non-existent-id"])
    assert existing == {item.id}


@pytest.mark.asyncio
async def test_get_existing_urls(db_session: AsyncSession):
    repo = NewsRepository(db_session)

    assert await repo.get_existing_urls([]) == set()

    item = NewsItemCreate(title="Item", summary="S", url="https://ex.com/article-1", source="src")
    await repo.save_news_items([item])

    existing = await repo.get_existing_urls(["https://ex.com/article-1", "https://ex.com/article-2"])
    assert existing == {"https://ex.com/article-1"}


@pytest.mark.asyncio
async def test_save_news_item_with_ai_score_and_reason(db_session: AsyncSession):
    repo = NewsRepository(db_session)
    item = NewsItemCreate(
        title="Top AI News",
        summary="Summary of important news",
        url="https://ex.com/ai-1",
        source="src",
        ai_score=9.5,
        ai_reason="Термінова подія національного значення",
    )
    saved = await repo.save_news_items([item])
    assert len(saved) == 1
    assert saved[0].ai_score == 9.5
    assert saved[0].ai_reason == "Термінова подія національного значення"

    fetched = await repo.get_by_id(item.id)
    assert fetched is not None
    assert fetched.ai_score == 9.5
    assert fetched.ai_reason == "Термінова подія національного значення"
    assert fetched.parsed_at is not None


@pytest.mark.asyncio
async def test_get_news_orders_by_parsed_at_desc(db_session: AsyncSession):
    repo = NewsRepository(db_session)
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    item_older = NewsItemCreate(
        title="Older Parsed",
        summary="Parsed earlier",
        url="https://ex.com/older",
        source="src",
        parsed_at=t1,
    )
    item_newer = NewsItemCreate(
        title="Newer Parsed",
        summary="Parsed later",
        url="https://ex.com/newer",
        source="src",
        parsed_at=t2,
    )

    await repo.save_news_items([item_older, item_newer])

    news = await repo.get_news(limit=10)
    assert len(news) >= 2
    assert news[0].title == "Newer Parsed"
    assert news[1].title == "Older Parsed"
    assert news[0].parsed_at > news[1].parsed_at


@pytest.mark.asyncio
async def test_get_unposted_top_news(db_session: AsyncSession):
    repo = NewsRepository(db_session)

    item_posted = NewsItemCreate(
        id="news-posted",
        title="Already Posted News",
        summary="S1",
        url="https://ex.com/p",
        source="src",
        ai_score=10.0,
    )
    item_unposted_high = NewsItemCreate(
        id="news-unposted-high",
        title="Unposted High Score",
        summary="S2",
        url="https://ex.com/u1",
        source="src",
        ai_score=9.0,
    )
    item_unposted_low = NewsItemCreate(
        id="news-unposted-low",
        title="Unposted Low Score",
        summary="S3",
        url="https://ex.com/u2",
        source="src",
        ai_score=6.0,
    )

    await repo.save_news_items([item_posted, item_unposted_high, item_unposted_low])

    # Create a Post for item_posted
    from app.models import Post, StatusType
    post = Post(news_id="news-posted", generated_text="Text", status=StatusType.PUBLISHED)
    db_session.add(post)
    await db_session.commit()

    # Query unposted
    unposted = await repo.get_unposted_top_news(limit=10)
    assert len(unposted) == 2
    assert unposted[0].id == "news-unposted-high"
    assert unposted[1].id == "news-unposted-low"

    # With exclude_ids
    unposted_filtered = await repo.get_unposted_top_news(limit=10, exclude_ids=["news-unposted-high"])
    assert len(unposted_filtered) == 1
    assert unposted_filtered[0].id == "news-unposted-low"


@pytest.mark.asyncio
async def test_get_unposted_top_news_filters_by_published_at_cutoff(db_session: AsyncSession):
    from datetime import UTC, datetime, timedelta

    repo = NewsRepository(db_session)
    now = datetime.now(UTC)

    fresh_item = NewsItemCreate(
        id="news-fresh",
        title="Fresh News",
        summary="S1",
        url="https://ex.com/fresh",
        source="src",
        ai_score=8.0,
        published_at=now - timedelta(hours=5),
    )
    stale_item = NewsItemCreate(
        id="news-stale",
        title="Stale News From Last Week",
        summary="S2",
        url="https://ex.com/stale",
        source="src",
        ai_score=10.0,  # Even though score is higher!
        published_at=now - timedelta(days=7),
    )

    await repo.save_news_items([fresh_item, stale_item])

    # With max_age_hours=48, stale_item must be excluded despite having higher score!
    unposted = await repo.get_unposted_top_news(limit=10, max_age_hours=48)
    assert len(unposted) == 1
    assert unposted[0].id == "news-fresh"


