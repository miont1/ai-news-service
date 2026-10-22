from unittest.mock import AsyncMock, patch

import pytest

from app.api.schemas import NewsItemCreate
from app.models import Source, SourceType
from app.services.news_service import NewsService


@pytest.mark.asyncio
async def test_news_service_with_db_keywords():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    service.keyword_repo.get_all_words = AsyncMock(return_value=["штучний інтелект"])

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

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_relevant])

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item_relevant, item_irrelevant])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news(use_db_keywords=True)

    assert result["sources_checked"] == 1
    assert result["total_found"] == 2
    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 1
    service.keyword_repo.get_all_words.assert_awaited_once()
    service.news_repo.save_news_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_news_service_with_explicit_keywords_ignores_db():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    service.keyword_repo.get_all_words = AsyncMock()

    item_ai = NewsItemCreate(title="AI revolution", summary="Tech", url="https://ex.com/1", source=fake_source.url)
    item_weather = NewsItemCreate(title="Sunny day", summary="Hot weather", url="https://ex.com/2", source=fake_source.url)

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_ai])

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item_ai, item_weather])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news(keywords=["AI"])

    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 1
    # DB keywords should NOT be queried when explicit keywords passed
    service.keyword_repo.get_all_words.assert_not_called()


@pytest.mark.asyncio
async def test_news_service_without_keywords_parses_all():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    service.keyword_repo.get_all_words = AsyncMock()

    item1 = NewsItemCreate(title="News 1", summary="Sum 1", url="https://ex.com/1", source=fake_source.url)
    item2 = NewsItemCreate(title="News 2", summary="Sum 2", url="https://ex.com/2", source=fake_source.url)

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item1, item2])

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item1, item2])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news(keywords=None, use_db_keywords=False)

    # When no keywords specified, all items pass
    assert result["total_found"] == 2
    assert result["relevant_matched"] == 2
    assert result["new_saved"] == 2
    service.keyword_repo.get_all_words.assert_not_called()


@pytest.mark.asyncio
async def test_news_service_skip_if_already_exists():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])

    item = NewsItemCreate(
        title="AI news",
        summary="Summary",
        url="https://example.com/ai",
        source=fake_source.url,
    )

    # Item ID already exists in DB
    service.news_repo.get_existing_ids = AsyncMock(return_value={item.id})
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock()

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock()) as mock_populate,
    ):
        result = await service.fetch_and_store_site_news(keywords=["AI"])

    assert result["total_found"] == 1
    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 0
    # raw_text fetching must NOT be called for duplicate
    mock_populate.assert_not_called()
    service.news_repo.save_news_items.assert_not_called()


@pytest.mark.asyncio
async def test_news_service_use_db_keywords_overrides_explicit_keywords():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])
    # Database has keyword "Україна"
    service.keyword_repo.get_all_words = AsyncMock(return_value=["Україна"])

    item_db = NewsItemCreate(title="Україна переможе", summary="Деталі", url="https://ex.com/1", source=fake_source.url)
    item_custom = NewsItemCreate(title="Трамп зробив заяву", summary="Політика", url="https://ex.com/2", source=fake_source.url)

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_db])

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item_db, item_custom])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        # Both use_db_keywords=True AND keywords=["Трамп"] are passed
        result = await service.fetch_and_store_site_news(keywords=["Трамп"], use_db_keywords=True)

    # use_db_keywords takes priority: only item_db matches ("Україна"), item_custom ("Трамп") is ignored
    assert result["relevant_matched"] == 1
    assert result["new_saved"] == 1
    service.keyword_repo.get_all_words.assert_awaited_once()


@pytest.mark.asyncio
async def test_news_service_partial_failure_continues_processing():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    source_fail = Source(id=1, name="Broken Source", url="https://broken.com/rss", type=SourceType.SITE, enabled=True)
    source_ok = Source(id=2, name="Working Source", url="https://working.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[source_fail, source_ok])

    item_ok_1 = NewsItemCreate(title="Valid News 1", summary="Sum 1", url="https://working.com/1", source=source_ok.url)
    item_ok_2 = NewsItemCreate(title="Valid News 2", summary="Sum 2", url="https://working.com/2", source=source_ok.url)

    async def mock_fetch_feed(url: str):
        if url == source_fail.url:
            raise ConnectionError("Connection Refused")
        return [item_ok_1, item_ok_2]

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_ok_1, item_ok_2])

    with (
        patch("app.services.news_service.fetch_rss_feed", side_effect=mock_fetch_feed),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news()

    assert result["sources_checked"] == 2
    assert result["sources_failed"] == 1
    assert len(result["failed_sources"]) == 1
    assert result["failed_sources"][0].source_name == "Broken Source"
    assert "Connection Refused" in result["failed_sources"][0].error
    assert result["total_found"] == 2
    assert result["new_saved"] == 2
    service.news_repo.save_news_items.assert_awaited_once()



@pytest.mark.asyncio
async def test_news_service_in_batch_deduplication():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    source1 = Source(id=1, name="Source 1", url="https://s1.com/rss", type=SourceType.SITE, enabled=True)
    source2 = Source(id=2, name="Source 2", url="https://s2.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[source1, source2])

    # Both sources return the exact same article (identical title, summary, url -> identical SHA-256 id)
    duplicate_item_1 = NewsItemCreate(
        title="Breaking Tech News",
        summary="A major announcement",
        url="https://original.com/news/1",
        source=source1.url,
    )
    duplicate_item_2 = NewsItemCreate(
        title="Breaking Tech News",
        summary="A major announcement",
        url="https://original.com/news/1",
        source=source2.url,
    )
    assert duplicate_item_1.id == duplicate_item_2.id

    async def mock_fetch_feed(url: str):
        if url == source1.url:
            return [duplicate_item_1]
        return [duplicate_item_2]

    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[duplicate_item_1])

    with (
        patch("app.services.news_service.fetch_rss_feed", side_effect=mock_fetch_feed),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        result = await service.fetch_and_store_site_news()

    # Total found is 2, but only 1 unique item should be saved
    assert result["total_found"] == 2
    assert result["new_saved"] == 1
    # Check that save_news_items was called with a single item
    saved_items_arg = service.news_repo.save_news_items.call_args[0][0]
    assert len(saved_items_arg) == 1


@pytest.mark.asyncio
async def test_news_service_skip_if_url_already_exists():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    fake_source = Source(id=1, name="Test Feed", url="https://example.com/rss", type=SourceType.SITE, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[fake_source])

    item = NewsItemCreate(
        title="AI news updated title",
        summary="Updated summary but same URL",
        url="https://example.com/same-url",
        source=fake_source.url,
    )

    # ID is new (not in DB), but URL already exists in DB!
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value={"https://example.com/same-url"})
    service.news_repo.save_news_items = AsyncMock()

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[item])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock()) as mock_populate,
    ):
        result = await service.fetch_and_store_site_news()

    assert result["total_found"] == 1
    assert result["new_saved"] == 0
    mock_populate.assert_not_called()
    service.news_repo.save_news_items.assert_not_called()



