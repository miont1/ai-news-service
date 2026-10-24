import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIConnectionError, RateLimitError

from app.ai.ranker import AINewsRanker
from app.api.schemas import NewsItemCreate


def _create_dummy_item(idx: int, title: str, summary: str = "Опис") -> NewsItemCreate:
    return NewsItemCreate(
        id=f"item-{idx}",
        title=title,
        summary=summary,
        url=f"https://example.com/{idx}",
        source="https://example.com/rss",
    )


@pytest.mark.asyncio
async def test_rank_news_empty_items():
    ranker = AINewsRanker()
    result = await ranker.rank_news([])
    assert result == []


@pytest.mark.asyncio
async def test_rank_news_skips_llm_when_count_less_or_equal_top_k():
    mock_client = AsyncMock()
    ranker = AINewsRanker(client=mock_client)

    items = [
        _create_dummy_item(1, "Новина 1"),
        _create_dummy_item(2, "Новина 2"),
    ]

    result = await ranker.rank_news(items, top_k=3)
    assert len(result) == 2
    assert result == items
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_rank_news_success_ranks_and_returns_top_3():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()

    json_payload = {
        "ranked_news": [
            {"index": 0, "score": 4.5, "reason": "Побутова новина"},
            {"index": 1, "score": 9.8, "reason": "Термінова політична заява"},
            {"index": 2, "score": 9.2, "reason": "Ключове рішення уряду"},
            {"index": 3, "score": 1.5, "reason": "Дрібний кримінал"},
            {"index": 4, "score": 8.7, "reason": "Міжнародна безпекова допомога"},
        ]
    }
    mock_choice.message.content = json.dumps(json_payload)
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    ranker = AINewsRanker(client=mock_client)

    items = [
        _create_dummy_item(0, "Новина 0"),
        _create_dummy_item(1, "Новина 1"),
        _create_dummy_item(2, "Новина 2"),
        _create_dummy_item(3, "Новина 3"),
        _create_dummy_item(4, "Новина 4"),
    ]

    top_items = await ranker.rank_news(items, top_k=3)

    assert len(top_items) == 3
    # Top 3 by score: 1 (9.8), 2 (9.2), 4 (8.7)
    assert [item.id for item in top_items] == ["item-1", "item-2", "item-4"]
    assert top_items[0].ai_score == 9.8
    assert top_items[0].ai_reason == "Термінова політична заява"
    assert top_items[1].ai_score == 9.2
    assert top_items[1].ai_reason == "Ключове рішення уряду"
    assert top_items[2].ai_score == 8.7
    assert top_items[2].ai_reason == "Міжнародна безпекова допомога"
    mock_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_rank_news_handles_markdown_wrapped_json():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()

    json_payload = {
        "ranked_news": [
            {"index": 0, "score": 3.0, "reason": "Локальна новина"},
            {"index": 1, "score": 9.0, "reason": "Важлива подія"},
            {"index": 2, "score": 8.0, "reason": "Цікава новина"},
            {"index": 3, "score": 7.0, "reason": "Помірна новина"},
        ]
    }
    mock_choice.message.content = f"```json\n{json.dumps(json_payload)}\n```"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    ranker = AINewsRanker(client=mock_client)
    items = [_create_dummy_item(i, f"Новина {i}") for i in range(4)]

    top_items = await ranker.rank_news(items, top_k=2)

    assert len(top_items) == 2
    assert [item.id for item in top_items] == ["item-1", "item-2"]
    assert top_items[0].ai_score == 9.0
    assert top_items[0].ai_reason == "Важлива подія"
    assert top_items[1].ai_score == 8.0
    assert top_items[1].ai_reason == "Цікава новина"


@pytest.mark.asyncio
async def test_rank_news_soft_fallback_on_invalid_json():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()

    mock_choice.message.content = "Невалідний JSON текст від моделі"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    ranker = AINewsRanker(client=mock_client)
    items = [_create_dummy_item(i, f"Новина {i}") for i in range(5)]

    # Soft fallback should return the first 3 items without crashing
    top_items = await ranker.rank_news(items, top_k=3)

    assert len(top_items) == 3
    assert [item.id for item in top_items] == ["item-0", "item-1", "item-2"]


@pytest.mark.asyncio
async def test_rank_news_soft_fallback_on_openai_error():
    mock_client = AsyncMock()
    mock_client.chat.completions.create.side_effect = RateLimitError(
        "Rate limit reached", response=MagicMock(status_code=429), body={}
    )

    ranker = AINewsRanker(client=mock_client)
    items = [_create_dummy_item(i, f"Новина {i}") for i in range(5)]

    # Soft fallback should log warning and return the first 3 items
    top_items = await ranker.rank_news(items, top_k=3)

    assert len(top_items) == 3
    assert [item.id for item in top_items] == ["item-0", "item-1", "item-2"]
