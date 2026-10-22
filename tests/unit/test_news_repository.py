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

