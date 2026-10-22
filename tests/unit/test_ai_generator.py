from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from app.ai.exceptions import (
    AIAuthenticationError,
    AIGenerationError,
    AIRateLimitError,
    AIServiceUnavailableError,
)
from app.ai.generator import PostGenerator
from app.ai.openai_client import get_openai_client


def create_mock_completion_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def test_get_openai_client():
    client = get_openai_client(api_key="test-key", base_url="https://api.example.com/v1")
    assert client.api_key == "test-key"
    assert str(client.base_url).startswith("https://api.example.com/v1")


@pytest.mark.asyncio
async def test_generate_post_success():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=create_mock_completion_response("🔥 **Новина AI**\n\nКороткий опис новини.\n\n#tech")
    )

    generator = PostGenerator(client=mock_client, model="gpt-4o-mini")
    result = await generator.generate_post(
        title="Новий прорив у штучному інтелекті",
        content="Компанія представила нову мовну модель із рекордною швидкістю.",
        source_url="https://example.com/news/1",
    )

    assert "🔥 **Новина AI**" in result
    assert mock_client.chat.completions.create.called
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    messages = call_kwargs["messages"]
    assert any(m["role"] == "system" for m in messages)
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "https://example.com/news/1" in user_content


@pytest.mark.asyncio
async def test_generate_post_with_summary_and_raw_text():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=create_mock_completion_response("Пост")
    )

    generator = PostGenerator(client=mock_client, model="gpt-4o-mini")
    await generator.generate_post(
        title="Заголовок",
        summary="Короткий зміст новини",
        raw_text="Повний текст новини з додатковими деталями.",
        source_url="https://example.com/item",
    )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Короткий зміст (Summary):\nКороткий зміст новини" in user_content
    assert "Повний текст статті:\nПовний текст новини з додатковими деталями." in user_content


@pytest.mark.asyncio
async def test_generate_post_empty_inputs_raises_value_error():
    generator = PostGenerator(client=MagicMock())
    with pytest.raises(ValueError, match="Both title and content cannot be empty"):
        await generator.generate_post(title="", content="")


@pytest.mark.asyncio
async def test_generate_post_empty_response_raises_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=create_mock_completion_response("")
    )

    generator = PostGenerator(client=mock_client)
    with pytest.raises(AIGenerationError, match="empty response"):
        await generator.generate_post(title="Заголовок", content="Опис")


@pytest.mark.asyncio
async def test_generate_post_authentication_error():
    mock_client = MagicMock()
    mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_response = httpx.Response(status_code=401, request=mock_request)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError("Invalid API key", response=mock_response, body=None)
    )

    generator = PostGenerator(client=mock_client)
    with pytest.raises(AIAuthenticationError):
        await generator.generate_post(title="Заголовок", content="Опис")


@pytest.mark.asyncio
async def test_generate_post_rate_limit_error():
    mock_client = MagicMock()
    mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_response = httpx.Response(status_code=429, request=mock_request)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RateLimitError("Rate limit reached", response=mock_response, body=None)
    )

    generator = PostGenerator(client=mock_client)
    with pytest.raises(AIRateLimitError):
        await generator.generate_post(title="Заголовок", content="Опис")


@pytest.mark.asyncio
async def test_generate_post_connection_error():
    mock_client = MagicMock()
    mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=mock_request)
    )

    generator = PostGenerator(client=mock_client)
    with pytest.raises(AIServiceUnavailableError):
        await generator.generate_post(title="Заголовок", content="Опис")


@pytest.mark.asyncio
async def test_generate_post_status_error():
    mock_client = MagicMock()
    mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_response = httpx.Response(status_code=500, request=mock_request)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIStatusError("Internal Server Error", response=mock_response, body=None)
    )

    generator = PostGenerator(client=mock_client)
    with pytest.raises(AIGenerationError):
        await generator.generate_post(title="Заголовок", content="Опис")
