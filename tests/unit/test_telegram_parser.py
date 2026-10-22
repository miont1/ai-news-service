from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from app.news_parser.exceptions import (
    TelegramChannelNotFoundError,
    TelegramChannelPrivateError,
    TelegramFloodWaitError,
    TelegramParserError,
    TelegramUnauthorizedError,
)
from app.news_parser.telegram import (
    clean_channel_username,
    clean_error_message,
    create_telegram_client,
    extract_summary,
    extract_title,
    fetch_channel_posts,
    get_telegram_client,
    is_meaningful_news_text,
)


class FakeMessage:
    """Mock Telethon message object."""

    def __init__(self, msg_id: int | None, text: str | None, date: datetime | None = None):
        self.id = msg_id
        self.message = text
        self.text = text
        self.date = date or datetime.now(UTC)


def test_clean_channel_username():
    assert clean_channel_username("@tech_news") == "tech_news"
    assert clean_channel_username("https://t.me/tech_news") == "tech_news"
    assert clean_channel_username("http://t.me/s/tech_news/") == "tech_news"
    assert clean_channel_username("t.me/tech_news") == "tech_news"
    assert clean_channel_username("telegram.me/tech_news?start=1") == "tech_news"
    assert clean_channel_username("tech_news") == "tech_news"
    assert clean_channel_username("  @tech_news  ") == "tech_news"
    assert clean_channel_username("") == ""
    assert clean_channel_username("   ") == ""

    # Private invite links must raise TelegramChannelPrivateError
    with pytest.raises(TelegramChannelPrivateError, match="private invite link"):
        clean_channel_username("https://t.me/joinchat/AAAAAFXAYpt1eJFeZdYxXw")

    with pytest.raises(TelegramChannelPrivateError, match="private invite link"):
        clean_channel_username("https://t.me/+AAAAAFXAYpt1eJFeZdYxXw")


def test_clean_error_message():
    # 1. Strips internal '(caused by ResolveUsernameRequest)'
    raw_rpc = RPCError(request=None, message="The key is not registered in the system")
    cleaned = clean_error_message(raw_rpc)
    assert "caused by" not in cleaned
    assert "The key is not registered in the system" in cleaned

    # 2. Strips RPC error code prefixes
    err_msg = "RPCError 401: Unauthorized access (caused by SomeInternalClass)"
    assert clean_error_message(Exception(err_msg)) == "Unauthorized access"



def test_extract_title():
    # 1. First line has a period within 120 chars -> cuts at period
    text_with_period = (
        "Україна отримала нову військову допомогу. У пакет увійшли системи ППО та снаряди.\n\n"
        "Деталі повідомив міністр оборони."
    )
    assert extract_title(text_with_period) == "Україна отримала нову військову допомогу"

    # 2. Numbered item like "1. Title. Details."
    numbered_text = "1. Перша важлива новина. Додатковий опис події.\nДругий рядок."
    assert extract_title(numbered_text) == "1. Перша важлива новина"

    # 3. Short first line without period -> returned as-is
    text_short = "Термінове повідомлення Генштабу\nТекст заяви..."
    assert extract_title(text_short) == "Термінове повідомлення Генштабу"

    # 4. Long first line (> 120 chars) without period -> truncated at word boundary with ellipsis
    long_first_line = (
        "Це дуже довге новинне повідомлення яке не містить жодної крапки в першому рядку "
        "і тому має бути акуратно обрізане до приблизно ста двадцяти символів із збереженням слів"
    )
    title = extract_title(long_first_line)
    assert len(title) <= 123
    assert title.endswith("...")

    # 5. Empty or whitespace text
    assert extract_title("") == ""
    assert extract_title("   \n\n  ") == ""


def test_extract_summary():
    # 1. Short text returns full text
    short = "Короткий опис новини в один рядок."
    assert extract_summary(short) == short

    # 2. Multi-sentence text cut at sentence boundary up to ~350 chars
    s1 = "Перше речення описує суть події на фронті. "
    s2 = "Друге речення додає важливі подробиці про міжнародну реакцію партнерів. "
    s3 = "Третє речення містить аналітику економічних наслідків для галузі. "
    s4 = "Четверте речення дуже довге і виходить далеко за межі допустимих чотирьохсот символів тексту новини."
    full = s1 + s2 + s3 + s4
    summary = extract_summary(full)
    assert summary.endswith(".")
    assert len(summary) <= 350
    assert "Перше речення" in summary
    assert "Друге речення" in summary

    # 3. Very long single sentence without punctuation
    no_punct = "довге_слово " * 50
    summary_no_punct = extract_summary(no_punct)
    assert len(summary_no_punct) <= 353
    assert summary_no_punct.endswith("...")

    # 4. Empty text
    assert extract_summary("") == ""


def test_is_meaningful_news_text():
    # User's exact example: stream announcement with link and brief thanks
    user_example = (
        "[НАЖИВО](https://youtube.com/live/aI8SfL0XvZc). Спілкування з медіа разом із Йонасом Гаром Стере й Александром Стуббом.\n"
        "Україна працює заради миру. Дякую партнерам за підтримку!"
    )
    assert is_meaningful_news_text(user_example, min_length=200) is False

    # Short alert / single sentence
    alert = "🚨 Повітряна тривога в Києві та області! Пройдіть в укриття."
    assert is_meaningful_news_text(alert, min_length=200) is False

    # Full news article
    real_news = (
        "Європейський Союз схвалив новий пакет допомоги для України на суму 5 мільярдів євро. "
        "Кошти підуть на підтримку економіки та відновлення критичної інфраструктури, яка постраждала "
        "внаслідок останніх обстрілів. Про це офіційно оголосила президентка Єврокомісії під час брифінгу."
    )
    assert is_meaningful_news_text(real_news, min_length=200) is True

    # Empty or whitespace
    assert is_meaningful_news_text("", min_length=200) is False
    assert is_meaningful_news_text("   ", min_length=200) is False


@pytest.mark.asyncio
async def test_fetch_channel_posts_success():
    pub_date = datetime(2026, 10, 22, 10, 30, tzinfo=UTC)
    msg1 = FakeMessage(
        msg_id=101,
        text=(
            "OpenAI представила нову модель. Вона працює втричі швидше за попередні версії "
            "та здатна вирішувати складні математичні та логічні задачі з високою точністю. "
            "Нові можливості вже доступні для всіх розробників за офіційним посиланням."
        ),
        date=pub_date,
    )
    msg2 = FakeMessage(
        msg_id=102,
        text=(
            "Короткий анонс події у сфері технологій та штучного інтелекту. Захід відбудеться "
            "наступного тижня за участі провідних світових експертів галузі та інженерів. "
            "Реєстрація вже відкрита для всіх охочих на сайті."
        ),
        date=pub_date,
    )

    mock_client = AsyncMock()
    mock_client.get_messages.return_value = [msg1, msg2]

    posts = await fetch_channel_posts(mock_client, "@openai_news", limit=10)

    assert len(posts) == 2
    mock_client.get_messages.assert_awaited_once_with("openai_news", limit=10)

    # Verify first item
    item1 = posts[0]
    assert item1.title == "OpenAI представила нову модель"
    assert "Вона працює втричі швидше" in item1.summary
    assert item1.raw_text == msg1.text
    assert item1.url == "https://t.me/openai_news/101"
    assert item1.source == "openai_news"
    assert item1.published_at == pub_date
    assert item1.id is not None

    # Verify second item
    item2 = posts[1]
    assert "Короткий анонс події" in item2.title
    assert item2.url == "https://t.me/openai_news/102"
    assert item2.source == "openai_news"


@pytest.mark.asyncio
async def test_fetch_channel_posts_skips_empty_and_service_messages():
    valid_long_text = (
        "Дійсна новина з текстом, яка є достатньо детальною та інформативною для нашого новинного сервісу. "
        "Вона містить розширений опис події, необхідні деталі для читача та перевищує встановлений ліміт "
        "у двісті символів для фільтрації мікроповідомлень."
    )
    mock_client = AsyncMock()
    mock_client.get_messages.return_value = [
        FakeMessage(msg_id=1, text=""),  # empty text
        FakeMessage(msg_id=2, text="   "),  # whitespace only
        FakeMessage(msg_id=3, text=None),  # service message without caption
        FakeMessage(msg_id=None, text=valid_long_text),  # invalid ID
        None,  # None object in list
        FakeMessage(msg_id=5, text=valid_long_text),  # valid
    ]

    posts = await fetch_channel_posts(mock_client, "t.me/valid_chan")

    assert len(posts) == 1
    assert "Дійсна новина" in posts[0].title
    assert posts[0].url == "https://t.me/valid_chan/5"


@pytest.mark.asyncio
async def test_fetch_channel_posts_skips_too_short_messages():
    """Verify that short messages like stream links or one-line announcements are skipped."""
    user_example = (
        "[НАЖИВО](https://youtube.com/live/aI8SfL0XvZc). Спілкування з медіа разом із Йонасом Гаром Стере й Александром Стуббом.\n"
        "Україна працює заради миру. Дякую партнерам за підтримку!"
    )
    mock_client = AsyncMock()
    mock_client.get_messages.return_value = [
        FakeMessage(msg_id=1, text=user_example),
        FakeMessage(msg_id=2, text="Короткий пост без посилань"),
    ]

    posts = await fetch_channel_posts(mock_client, "@news_chan", min_text_length=200)
    assert len(posts) == 0


@pytest.mark.asyncio
async def test_fetch_channel_posts_with_iter_messages():
    """Verify support for client that provides iter_messages instead of get_messages."""
    msg = FakeMessage(
        msg_id=42,
        text=(
            "Новина через iter_messages містить повний інформаційний блок новинного характеру, "
            "який успішно проходить валідацію за мінімальною довжиною тексту для збереження в базу. "
            "Додатковий контекст повідомлення забезпечує перевищення встановленого порогу довжини."
        ),
    )

    async def fake_iter_messages(channel, limit=20):
        yield msg

    mock_client = MagicMock(spec=["iter_messages"])
    mock_client.iter_messages = fake_iter_messages

    posts = await fetch_channel_posts(mock_client, "@chan_iter")
    assert len(posts) == 1
    assert posts[0].url == "https://t.me/chan_iter/42"


@pytest.mark.asyncio
async def test_fetch_channel_posts_empty_channel_name():
    mock_client = AsyncMock()
    posts = await fetch_channel_posts(mock_client, "")
    assert posts == []
    mock_client.get_messages.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_channel_posts_errors():
    mock_client = AsyncMock()

    # 1. UsernameNotOccupiedError -> TelegramChannelNotFoundError
    mock_client.get_messages.side_effect = UsernameNotOccupiedError(request=None)
    with pytest.raises(TelegramChannelNotFoundError):
        await fetch_channel_posts(mock_client, "@non_existent_channel")

    # 2. UsernameInvalidError -> TelegramChannelNotFoundError
    mock_client.get_messages.side_effect = UsernameInvalidError(request=None)
    with pytest.raises(TelegramChannelNotFoundError):
        await fetch_channel_posts(mock_client, "@invalid!!!")

    # 3. ChannelPrivateError -> TelegramChannelPrivateError
    mock_client.get_messages.side_effect = ChannelPrivateError(request=None)
    with pytest.raises(TelegramChannelPrivateError):
        await fetch_channel_posts(mock_client, "@private_chan")

    # 4. ChannelInvalidError -> TelegramChannelPrivateError
    mock_client.get_messages.side_effect = ChannelInvalidError(request=None)
    with pytest.raises(TelegramChannelPrivateError):
        await fetch_channel_posts(mock_client, "@invalid_chan")

    # 5. FloodWaitError -> TelegramFloodWaitError
    flood_err = FloodWaitError(request=None)
    flood_err.seconds = 45
    mock_client.get_messages.side_effect = flood_err
    with pytest.raises(TelegramFloodWaitError):
        await fetch_channel_posts(mock_client, "@flood_chan")

    # 6. AuthKeyUnregisteredError -> TelegramUnauthorizedError
    mock_client.get_messages.side_effect = AuthKeyUnregisteredError(request=None)
    with pytest.raises(TelegramUnauthorizedError):
        await fetch_channel_posts(mock_client, "@unauth_chan")

    # 7. General RPCError -> TelegramParserError
    mock_client.get_messages.side_effect = RPCError(request=None, message="Internal Telegram RPC failure", code=500)
    with pytest.raises(TelegramParserError):
        await fetch_channel_posts(mock_client, "@rpc_chan")

    # 7. Network ConnectionError -> TelegramParserError
    mock_client.get_messages.side_effect = ConnectionError("Reset by peer")
    with pytest.raises(TelegramParserError):
        await fetch_channel_posts(mock_client, "@net_chan")

    # 8. ValueError (entity not resolved) -> TelegramChannelNotFoundError
    mock_client.get_messages.side_effect = ValueError("Cannot find any entity")
    with pytest.raises(TelegramChannelNotFoundError):
        await fetch_channel_posts(mock_client, "@unknown_entity")


@pytest.mark.asyncio
async def test_get_telegram_client_with_provided_client():
    mock_client = AsyncMock()
    async with get_telegram_client(client=mock_client) as client:
        assert client is mock_client
    # Should not call connect or disconnect on provided client
    mock_client.connect.assert_not_called()
    mock_client.disconnect.assert_not_called()


def test_create_telegram_client_missing_credentials():
    with patch("app.news_parser.telegram.settings") as mock_settings:
        mock_settings.TG_API_ID = None
        mock_settings.TG_API_HASH = None
        with pytest.raises(ValueError, match="Telegram credentials not configured"):
            create_telegram_client()
