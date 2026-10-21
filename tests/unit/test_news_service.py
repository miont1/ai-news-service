from unittest.mock import AsyncMock, patch

import pytest

from app.api.schemas import NewsItemCreate
from app.models import Source, SourceType
from app.services.news_service import NewsService


@pytest.mark.asyncio
async def test_news_service_full_pipeline():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    # 1. Mock sources & keywords
    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    service.keyword_repo.get_all_words = AsyncMock(return_value=["штучний інтелект"])

    # 2. Mock items parsed from RSS
    item_relevant = NewsItemCreate(
        title="Штучний інтелект змінює світ",
        summary="Огляд новинок",
        url="https://example.com/ai-1",
        source=fake_source.url,
    )
    item_irrelevant = NewsItemCreate(
        title="Прогноз погоди",
        summary="Сонячно та тепло",
        url="https://example.com/weather-1",
        source=fake_source.url,
    )

    # 3. Mock DB deduplication (no existing IDs)
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_relevant])

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item_relevant, item_irrelevant])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news()

    assert result["sources_checked"] == 1
    assert result["total_found"] == 2
    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 1
    service.news_repo.save_news_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_news_service_skip_if_already_exists():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    service.keyword_repo.get_all_words = AsyncMock(return_value=["AI"])

    item = NewsItemCreate(
        title="AI news",
        summary="Summary",
        url="https://example.com/ai",
        source=fake_source.url,
    )

    # Item ID already exists in DB
    service.news_repo.get_existing_ids = AsyncMock(return_value={item.id})
    service.news_repo.save_news_items = AsyncMock()

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock()) as mock_populate,
    ):
        result = await service.fetch_and_store_site_news()

    assert result["total_found"] == 1
    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 0
    # raw_text fetching must NOT be called for duplicate
    mock_populate.assert_not_called()
    service.news_repo.save_news_items.assert_not_called()
