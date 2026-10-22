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


# ==============================================================================
# Telegram News Service Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_telegram_news_no_active_sources():
    mock_session = AsyncMock()
    service = NewsService(mock_session)
    service.source_repo.get_active_sources = AsyncMock(return_value=[])

    result = await service.fetch_and_store_telegram_news()

    assert result["sources_checked"] == 0
    assert result["news_found"] == 0
    assert result["news_stored"] == 0
    assert "No active Telegram sources found" in result["message"]
    service.source_repo.get_active_sources.assert_awaited_once_with(SourceType.TG)


@pytest.mark.asyncio
async def test_telegram_news_missing_credentials():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    tg_source = Source(id=1, name="TG Tech", url="@tech_ua", type=SourceType.TG, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[tg_source])

    with patch("app.news_parser.telegram.settings") as mock_settings:
        mock_settings.TG_API_ID = None
        mock_settings.TG_API_HASH = None

        result = await service.fetch_and_store_telegram_news(client=None)

    assert result["sources_checked"] == 1
    assert result["sources_failed"] == 1
    assert len(result["failed_sources"]) == 1
    assert "credentials not configured" in result["failed_sources"][0].error
    assert result["news_found"] == 0
    assert result["news_stored"] == 0


@pytest.mark.asyncio
async def test_telegram_news_success_with_client():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    tg_source = Source(id=1, name="TG Tech", url="@tech_ua", type=SourceType.TG, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[tg_source])

    item1 = NewsItemCreate(
        title="Новий реліз Python 3.14",
        summary="Вийшла нова версія мови з покращеною продуктивністю.",
        raw_text="Вийшла нова версія мови Python 3.14 з покращеною продуктивністю.",
        url="https://t.me/tech_ua/101",
        source="tech_ua",
    )
    item2 = NewsItemCreate(
        title="Штучний інтелект у медицині",
        summary="AI допомагає ставити діагнози швидше.",
        raw_text="AI допомагає ставити діагнози швидше за лікарів.",
        url="https://t.me/tech_ua/102",
        source="tech_ua",
    )

    mock_client = AsyncMock()
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item1, item2])

    with patch("app.services.news_service.fetch_channel_posts", new=AsyncMock(return_value=[item1, item2])):
        result = await service.fetch_and_store_telegram_news(limit_per_channel=15, client=mock_client)

    assert result["sources_checked"] == 1
    assert result["sources_failed"] == 0
    assert result["news_found"] == 2
    assert result["total_found"] == 2
    assert result["relevant_matched"] == 2
    assert result["news_stored"] == 2
    assert result["new_saved"] == 2
    service.news_repo.save_news_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_news_keyword_filtering():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    tg_source = Source(id=1, name="TG News", url="t.me/channel_news", type=SourceType.TG, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[tg_source])

    item_ai = NewsItemCreate(
        title="Революція AI",
        summary="Моделі нового покоління",
        raw_text="Повний текст новини про AI",
        url="https://t.me/channel_news/1",
        source="channel_news",
    )
    item_weather = NewsItemCreate(
        title="Прогноз погоди",
        summary="Сьогодні очікується дощ",
        raw_text="Повний текст прогнозу погоди",
        url="https://t.me/channel_news/2",
        source="channel_news",
    )

    mock_client = AsyncMock()
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[item_ai])

    with patch("app.services.news_service.fetch_channel_posts", new=AsyncMock(return_value=[item_ai, item_weather])):
        result = await service.fetch_and_store_telegram_news(keywords=["AI"], client=mock_client)

    assert result["news_found"] == 2
    assert result["relevant_matched"] == 1
    assert result["news_stored"] == 1
    # Verify only item_ai was passed to save_news_items
    saved_items = service.news_repo.save_news_items.call_args[0][0]
    assert len(saved_items) == 1
    assert saved_items[0].url == item_ai.url


@pytest.mark.asyncio
async def test_telegram_news_deduplication():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    source1 = Source(id=1, name="Channel 1", url="@chan1", type=SourceType.TG, enabled=True)
    source2 = Source(id=2, name="Channel 2", url="@chan2", type=SourceType.TG, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[source1, source2])

    item_duplicate_1 = NewsItemCreate(
        title="Термінова заява",
        summary="Опис заяви",
        raw_text="Повний текст",
        url="https://t.me/orig/10",
        source="chan1",
    )
    item_duplicate_2 = NewsItemCreate(
        title="Термінова заява",
        summary="Опис заяви",
        raw_text="Повний текст",
        url="https://t.me/orig/10",
        source="chan2",
    )
    item_already_in_db = NewsItemCreate(
        title="Стара новина",
        summary="Вже збережена",
        raw_text="Повний текст",
        url="https://t.me/orig/5",
        source="chan1",
    )

    async def fake_fetch(client, url, limit=20, **kwargs):
        if url == "@chan1":
            return [item_duplicate_1, item_already_in_db]
        return [item_duplicate_2]

    mock_client = AsyncMock()
    # item_already_in_db URL is already in database
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value={"https://t.me/orig/5"})
    service.news_repo.save_news_items = AsyncMock(return_value=[item_duplicate_1])

    with patch("app.services.news_service.fetch_channel_posts", side_effect=fake_fetch):
        result = await service.fetch_and_store_telegram_news(client=mock_client)

    # Total found = 3 (item1, old_item, item2)
    # item_duplicate_2 is dropped by in-batch dedup (same url as item_duplicate_1)
    # item_already_in_db is dropped by DB dedup
    # Only 1 unique item saved
    assert result["news_found"] == 3
    assert result["news_stored"] == 1
    assert result["new_saved"] == 1
    saved_items = service.news_repo.save_news_items.call_args[0][0]
    assert len(saved_items) == 1
    assert saved_items[0].url == item_duplicate_1.url


@pytest.mark.asyncio
async def test_telegram_news_partial_failure():
    mock_session = AsyncMock()
    service = NewsService(mock_session)

    broken_source = Source(id=1, name="Broken Channel", url="@broken_chan", type=SourceType.TG, enabled=True)
    working_source = Source(id=2, name="Working Channel", url="@working_chan", type=SourceType.TG, enabled=True)
    service.source_repo.get_active_sources = AsyncMock(return_value=[broken_source, working_source])

    valid_item = NewsItemCreate(
        title="Успішна новина",
        summary="Опис успіху",
        raw_text="Повний текст успішної новини",
        url="https://t.me/working_chan/1",
        source="working_chan",
    )

    async def fake_fetch(client, url, limit=20, **kwargs):
        if url == broken_source.url:
            raise ConnectionError("Telegram network timeout")
        return [valid_item]

    mock_client = AsyncMock()
    service.news_repo.get_existing_ids = AsyncMock(return_value=set())
    service.news_repo.get_existing_urls = AsyncMock(return_value=set())
    service.news_repo.save_news_items = AsyncMock(return_value=[valid_item])

    with patch("app.services.news_service.fetch_channel_posts", side_effect=fake_fetch):
        result = await service.fetch_and_store_telegram_news(client=mock_client)

    assert result["sources_checked"] == 2
    assert result["sources_failed"] == 1
    assert len(result["failed_sources"]) == 1
    assert result["failed_sources"][0].source_name == "Broken Channel"
    assert "Telegram network timeout" in result["failed_sources"][0].error
    assert result["news_found"] == 1
    assert result["news_stored"] == 1
    service.news_repo.save_news_items.assert_awaited_once()




