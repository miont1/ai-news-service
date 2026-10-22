import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from telethon import TelegramClient, utils
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession

from app.api.schemas import NewsItemCreate
from app.config import settings
from app.news_parser.exceptions import (
    TelegramChannelNotFoundError,
    TelegramChannelPrivateError,
    TelegramFloodWaitError,
    TelegramParserError,
    TelegramUnauthorizedError,
)

__all__ = [
    "TelegramChannelNotFoundError",
    "TelegramChannelPrivateError",
    "TelegramFloodWaitError",
    "TelegramParserError",
    "TelegramUnauthorizedError",
    "clean_channel_username",
    "clean_error_message",
    "create_telegram_client",
    "extract_summary",
    "extract_title",
    "fetch_channel_posts",
    "get_telegram_client",
    "is_meaningful_news_text",
]

logger = logging.getLogger(__name__)


def clean_error_message(e: Exception) -> str:
    """Extract clean error text without leaking internal Telethon RPC request classes."""
    msg = str(e)
    # Strip any internal "(caused by <RequestName>)"
    cleaned = re.sub(r"\s*\(caused by [^)]+\)", "", msg).strip()
    # Strip leading "RPCError <code/None>: "
    cleaned = re.sub(r"^RPCError\s*(\w+)?:\s*", "", cleaned).strip()
    return cleaned


def clean_channel_username(channel: str) -> str:
    """Normalize various Telegram channel identifiers into a clean username.

    Raises TelegramChannelPrivateError if a private invite link is provided instead
    of a public channel username.
    """
    if not channel or not channel.strip():
        return ""
    cleaned = channel.strip()
    # Strip URL fragments or query parameters if present
    cleaned = cleaned.split("?")[0].split("#")[0]
    # Remove /s/ web preview prefix if present (e.g. t.me/s/channel -> t.me/channel)
    cleaned = re.sub(r"/(?:s)/", "/", cleaned, flags=re.IGNORECASE)

    # Use Telethon's built-in username parser
    username, is_invite = utils.parse_username(cleaned)
    if is_invite:
        raise TelegramChannelPrivateError(
            f"Channel '{channel}' is a private invite link. Only public channels (@channel or t.me/channel) are supported."
        )

    if username:
        return username

    raw_clean = cleaned.strip("/").lstrip("@").strip()
    if raw_clean.startswith("joinchat/") or raw_clean.startswith("+"):
        raise TelegramChannelPrivateError(
            f"Channel '{channel}' is a private invite link. Only public channels (@channel or t.me/channel) are supported."
        )

    return raw_clean


def is_meaningful_news_text(text: str, min_length: int = 200) -> bool:
    """Check if the message contains substantial text rather than just a short alert/link.

    Strips markdown links and standalone URLs before checking length, ensuring that
    short stream links, brief quotes, alerts, or single photos without article text are ignored.
    """
    if not text or not text.strip():
        return False
    if min_length <= 0:
        return True
    # Strip markdown link URLs: [title](url) -> title
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Strip standalone URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = " ".join(cleaned.split())
    return len(cleaned) >= min_length


def extract_title(text: str, max_length: int = 120) -> str:
    """Extract a concise title from the message.

    Takes the first line and cuts it at the first sentence period (~120 chars)
    or truncates at a word boundary up to max_length.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    first_line = lines[0]

    dot_idx = first_line.find(".")
    # If period is part of a list number like '1.', look for subsequent period
    if 0 < dot_idx < 3 and len(first_line) > dot_idx + 1:
        next_dot = first_line.find(".", dot_idx + 1)
        if 0 < next_dot <= max_length:
            dot_idx = next_dot
        else:
            dot_idx = -1

    if 3 < dot_idx <= max_length:
        candidate = first_line[:dot_idx].strip()
        if candidate:
            return candidate

    if len(first_line) > max_length:
        truncated = first_line[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > 30:
            return truncated[:last_space].strip() + "..."
        return truncated.strip() + "..."

    return first_line


def extract_summary(text: str, max_length: int = 350) -> str:
    """Extract summary from the first few sentences (up to ~300-400 characters)."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    if len(cleaned) <= max_length:
        return cleaned

    truncated = cleaned[:max_length]
    best_punct = -1
    for match in re.finditer(r"[.!?](?=\s|$)", truncated):
        best_punct = match.end()

    if best_punct > 80:
        return cleaned[:best_punct].strip()

    last_space = truncated.rfind(" ")
    if last_space > 80:
        return truncated[:last_space].strip() + "..."

    return truncated.strip() + "..."


def create_telegram_client(
    session: str | None = None,
    api_id: int | None = None,
    api_hash: str | None = None,
) -> TelegramClient:
    """Initialize a Telethon TelegramClient using settings or explicit arguments."""
    resolved_api_id = api_id if api_id is not None else settings.TG_API_ID
    resolved_api_hash = api_hash if api_hash is not None else settings.TG_API_HASH

    if not resolved_api_id or not resolved_api_hash:
        raise ValueError(
            "Telegram credentials not configured: TG_API_ID and TG_API_HASH are required"
        )

    if session:
        client_session = session
    elif settings.TG_SESSION_STRING:
        client_session = StringSession(settings.TG_SESSION_STRING)
    else:
        client_session = settings.TG_SESSION_NAME

    return TelegramClient(
        client_session,
        int(resolved_api_id),
        resolved_api_hash,
    )


@asynccontextmanager
async def get_telegram_client(
    client: TelegramClient | None = None,
) -> AsyncIterator[TelegramClient]:
    """Context manager providing a connected TelegramClient instance.

    If a client is explicitly supplied, yields it directly without reconnecting.
    Otherwise, creates, connects and automatically disconnects the client.
    """
    if client is not None:
        yield client
        return

    tg_client = create_telegram_client()
    await tg_client.connect()
    try:
        if not await tg_client.is_user_authorized():
            raise TelegramUnauthorizedError(
                "Telegram session is not authorized. Please log in with your Telegram account (run 'uv run python scripts/auth_telegram.py')."
            )
        yield tg_client
    finally:
        if tg_client.is_connected():
            await tg_client.disconnect()


async def fetch_channel_posts(
    client: Any,
    channel: str,
    limit: int = 20,
    min_text_length: int = 200,
) -> list[NewsItemCreate]:
    """Fetch the latest posts from a public Telegram channel.

    Args:
        client: Connected TelegramClient (or AsyncMock for testing).
        channel: Channel identifier (@name, t.me/name, or name).
        limit: Number of recent posts to inspect.
        min_text_length: Minimum character length (excluding links) required to be a news item.

    Returns:
        List of parsed NewsItemCreate objects.

    Raises:
        TelegramChannelNotFoundError: Channel username does not exist or is invalid.
        TelegramChannelPrivateError: Channel is private, invite-only or access is denied.
        TelegramFloodWaitError: Telegram rate limiting triggered.
        TelegramUnauthorizedError: Telegram session is not logged in.
        TelegramParserError: General RPC or network failure.
    """
    clean_name = clean_channel_username(channel)
    if not clean_name:
        logger.warning("Empty or invalid channel name provided: '%s'", channel)
        return []

    try:
        if hasattr(client, "get_messages"):
            raw_result = client.get_messages(clean_name, limit=limit)
            if hasattr(raw_result, "__await__"):
                messages = await raw_result
            else:
                messages = raw_result
        elif hasattr(client, "iter_messages"):
            messages = [msg async for msg in client.iter_messages(clean_name, limit=limit)]
        else:
            raise AttributeError("Provided client has neither 'get_messages' nor 'iter_messages'")
    except (UsernameNotOccupiedError, UsernameInvalidError) as e:
        logger.warning("Telegram channel '%s' not found: %s", channel, e)
        raise TelegramChannelNotFoundError(f"Channel '{channel}' not found: {clean_error_message(e)}") from e
    except (ChannelPrivateError, ChannelInvalidError) as e:
        logger.warning("Telegram channel '%s' is private or inaccessible: %s", channel, e)
        raise TelegramChannelPrivateError(f"Channel '{channel}' is private or inaccessible: {clean_error_message(e)}") from e
    except FloodWaitError as e:
        logger.warning("Telegram flood wait on channel '%s': %s seconds", channel, e.seconds)
        raise TelegramFloodWaitError(f"Telegram rate limit: flood wait {e.seconds}s") from e
    except AuthKeyUnregisteredError as e:
        logger.warning("Telegram session is not authorized: %s", e)
        raise TelegramUnauthorizedError(
            "Telegram session is not authorized. Please log in with your Telegram account (run 'uv run python scripts/auth_telegram.py')."
        ) from e
    except RPCError as e:
        logger.warning("Telegram RPC error fetching channel '%s': %s", channel, e)
        raise TelegramParserError(f"Telegram error for '{channel}': {clean_error_message(e)}") from e
    except (ConnectionError, OSError) as e:
        logger.warning("Network connection failure fetching channel '%s': %s", channel, e)
        raise TelegramParserError(f"Network error connecting to Telegram for '{channel}'") from e
    except ValueError as e:
        logger.warning("Could not resolve Telegram entity for '%s': %s", channel, e)
        raise TelegramChannelNotFoundError(f"Could not resolve Telegram channel '{channel}'") from e

    items: list[NewsItemCreate] = []
    for msg in messages:
        if msg is None:
            continue

        raw_text = (getattr(msg, "message", None) or getattr(msg, "text", None) or "").strip()
        # Skip empty / service messages or messages that are too short to be considered news
        if not is_meaningful_news_text(raw_text, min_length=min_text_length):
            continue

        msg_id = getattr(msg, "id", None)
        if not msg_id:
            continue

        title = extract_title(raw_text)
        summary = extract_summary(raw_text)
        url = f"https://t.me/{clean_name}/{msg_id}"

        # Ensure UTC timezone for publication date
        msg_date = getattr(msg, "date", None)
        if msg_date is None:
            published_at = datetime.now(UTC)
        elif msg_date.tzinfo is None:
            published_at = msg_date.replace(tzinfo=UTC)
        else:
            published_at = msg_date.astimezone(UTC)

        items.append(
            NewsItemCreate(
                title=title,
                summary=summary,
                raw_text=raw_text,
                url=url,
                source=clean_name,
                published_at=published_at,
            )
        )

    return items
