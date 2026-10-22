from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.api.schemas import NewsItemCreate
from app.repositories.news_repository import NewsRepository


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# ==========================================
# Sources API Tests
# ==========================================

@pytest.mark.asyncio
async def test_sources_crud_flow(client: AsyncClient):
    # 1. Create source
    source_payload = {
        "name": "Radio Svoboda",
        "url": "https://www.radiosvoboda.org/rss",
        "type": "site",
        "enabled": True,
    }
    create_res = await client.post("/api/sources", json=source_payload)
    assert create_res.status_code == 201
    source_data = create_res.json()
    source_id = source_data["id"]
    assert source_data["name"] == "Radio Svoboda"
    assert source_data["url"] == "https://www.radiosvoboda.org/rss"

    # 2. Duplicate source URL -> 409 Conflict
    dup_res = await client.post("/api/sources", json=source_payload)
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"]

    # 3. List sources
    list_res = await client.get("/api/sources")
    assert list_res.status_code == 200
    sources = list_res.json()
    assert len(sources) == 1
    assert sources[0]["id"] == source_id

    # 4. Update source
    update_res = await client.put(f"/api/sources/{source_id}", json={"name": "Radio Liberty Updated"})
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Radio Liberty Updated"

    # 5. Delete source
    del_res = await client.delete(f"/api/sources/{source_id}")
    assert del_res.status_code == 204

    # 6. Delete again -> 404 Not Found
    del_again_res = await client.delete(f"/api/sources/{source_id}")
    assert del_again_res.status_code == 404


@pytest.mark.asyncio
async def test_sources_edge_cases(client: AsyncClient):
    # Validation error on empty name or url
    res_empty_name = await client.post("/api/sources", json={"name": "   ", "url": "https://valid.com", "type": "site"})
    assert res_empty_name.status_code == 422

    res_empty_url = await client.post("/api/sources", json={"name": "Valid", "url": "   ", "type": "site"})
    assert res_empty_url.status_code == 422

    # 404 on update non-existent source
    res_404 = await client.put("/api/sources/9999", json={"name": "Ghost"})
    assert res_404.status_code == 404

    # Self-update: updating with same url must NOT trigger 409 Conflict
    created = await client.post("/api/sources", json={"name": "Source A", "url": "https://source-a.com", "type": "site"})
    source_id = created.json()["id"]

    self_update = await client.put(f"/api/sources/{source_id}", json={"url": "https://source-a.com", "name": "Source A Updated"})
    assert self_update.status_code == 200
    assert self_update.json()["name"] == "Source A Updated"


@pytest.mark.asyncio
async def test_update_source_duplicate_url_conflict(client: AsyncClient):
    await client.post("/api/sources", json={"name": "Source 1", "url": "https://url1.com", "type": "site"})
    res2 = await client.post("/api/sources", json={"name": "Source 2", "url": "https://url2.com", "type": "site"})
    source2_id = res2.json()["id"]

    # Try updating source2 to source1's URL -> 409 Conflict
    update_res = await client.put(f"/api/sources/{source2_id}", json={"url": "https://url1.com"})
    assert update_res.status_code == 409
    assert "already exists" in update_res.json()["detail"]


# ==========================================
# Keywords API Tests
# ==========================================

@pytest.mark.asyncio
async def test_keywords_crud_flow(client: AsyncClient):
    # 1. Create keyword with extra whitespace
    create_res = await client.post("/api/keywords", json={"word": "  Штучний  Інтелект  "})
    assert create_res.status_code == 201
    keyword_data = create_res.json()
    keyword_id = keyword_data["id"]
    # Stripped whitespace
    assert keyword_data["word"] == "Штучний Інтелект"

    # 2. Duplicate keyword (case-insensitive) -> 409 Conflict
    dup_res = await client.post("/api/keywords", json={"word": "штучний інтелект"})
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"]

    # 3. List keywords
    list_res = await client.get("/api/keywords")
    assert list_res.status_code == 200
    keywords = list_res.json()
    assert len(keywords) == 1
    assert keywords[0]["id"] == keyword_id

    # 4. Update keyword
    update_res = await client.put(f"/api/keywords/{keyword_id}", json={"word": "AI"})
    assert update_res.status_code == 200
    assert update_res.json()["word"] == "AI"

    # 5. Delete keyword
    del_res = await client.delete(f"/api/keywords/{keyword_id}")
    assert del_res.status_code == 204

    # 6. Delete again -> 404 Not Found
    del_again_res = await client.delete(f"/api/keywords/{keyword_id}")
    assert del_again_res.status_code == 404


@pytest.mark.asyncio
async def test_keywords_edge_cases(client: AsyncClient):
    # 1. Validation error on empty or whitespace keyword
    res_empty = await client.post("/api/keywords", json={"word": "   "})
    assert res_empty.status_code == 422

    res_empty_str = await client.post("/api/keywords", json={"word": ""})
    assert res_empty_str.status_code == 422

    # 2. 404 on update non-existent keyword
    res_404 = await client.put("/api/keywords/9999", json={"word": "NonExistent"})
    assert res_404.status_code == 404

    # 3. Self-update: updating keyword with its own word (or same word case-insensitively)
    created = await client.post("/api/keywords", json={"word": "Golang"})
    kw_id = created.json()["id"]

    self_update_same = await client.put(f"/api/keywords/{kw_id}", json={"word": "Golang"})
    assert self_update_same.status_code == 200

    self_update_casing = await client.put(f"/api/keywords/{kw_id}", json={"word": "golang"})
    assert self_update_casing.status_code == 200
    assert self_update_casing.json()["word"] == "golang"


@pytest.mark.asyncio
async def test_update_keyword_duplicate_conflict(client: AsyncClient):
    await client.post("/api/keywords", json={"word": "Python"})
    res2 = await client.post("/api/keywords", json={"word": "FastAPI"})
    keyword2_id = res2.json()["id"]

    # Try updating keyword2 to "python" (case-insensitive duplicate) -> 409 Conflict
    update_res = await client.put(f"/api/keywords/{keyword2_id}", json={"word": "python"})
    assert update_res.status_code == 409
    assert "already exists" in update_res.json()["detail"]


# ==========================================
# News API Tests
# ==========================================

@pytest.mark.asyncio
async def test_get_news_empty(client: AsyncClient):
    res = await client.get("/api/news")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_get_news_pagination_and_validation(client: AsyncClient, db_session):
    repo = NewsRepository(db_session)
    # Populate 4 items
    items = [
        NewsItemCreate(title=f"Article {i}", summary=f"Summary {i}", url=f"https://ex.com/{i}", source="src", published_at=datetime.now(UTC))
        for i in range(1, 5)
    ]
    await repo.save_news_items(items)

    # 1. limit=2, offset=1
    res_page = await client.get("/api/news?limit=2&offset=1")
    assert res_page.status_code == 200
    page_items = res_page.json()
    assert len(page_items) == 2

    # 2. limit=0 -> 422 Unprocessable Entity
    res_zero_limit = await client.get("/api/news?limit=0")
    assert res_zero_limit.status_code == 422

    # 3. Large offset -> empty list
    res_large_offset = await client.get("/api/news?limit=10&offset=500")
    assert res_large_offset.status_code == 200
    assert res_large_offset.json() == []


@pytest.mark.asyncio
async def test_fetch_news_no_active_sources(client: AsyncClient):
    res = await client.post("/api/news/fetch", json={})
    assert res.status_code == 200
    data = res.json()
    assert data["sources_checked"] == 0
    assert data["new_saved"] == 0
    assert "No active site sources found" in data["message"]


@pytest.mark.asyncio
async def test_fetch_news_pipeline_integration(client: AsyncClient):
    # 1. Create source and keywords in DB
    await client.post("/api/sources", json={"name": "Test Site", "url": "https://test.com/rss", "type": "site"})
    await client.post("/api/keywords", json={"word": "технології"})

    mock_news_1 = NewsItemCreate(
        title="Новини про технології майбутнього",
        summary="Огляд інновацій",
        url="https://test.com/1",
        source="https://test.com/rss",
    )
    mock_news_2 = NewsItemCreate(
        title="Спорт сьогодні",
        summary="Футбольний матч",
        url="https://test.com/2",
        source="https://test.com/rss",
    )

    with (
        patch("app.services.news_service.fetch_rss_feed", new=AsyncMock(return_value=[mock_news_1, mock_news_2])),
        patch("app.services.news_service.populate_articles_raw_text", new=AsyncMock(side_effect=lambda items: items)),
    ):
        # 2. Trigger fetch with use_db_keywords=True
        fetch_res = await client.post("/api/news/fetch", json={"use_db_keywords": True})
        assert fetch_res.status_code == 200
        stats = fetch_res.json()
        assert stats["sources_checked"] == 1
        assert stats["total_found"] == 2
        assert stats["relevant_matched"] == 1
        assert stats["new_saved"] == 1

    # 3. Verify news is saved in DB and available via GET /api/news
    get_res = await client.get("/api/news")
    assert get_res.status_code == 200
    news_list = get_res.json()
    assert len(news_list) == 1
    assert news_list[0]["title"] == "Новини про технології майбутнього"
    assert news_list[0]["url"] == "https://test.com/1"
