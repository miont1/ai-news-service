class TelegramParserError(Exception):
    """Base exception for Telegram parser errors."""


class TelegramChannelNotFoundError(TelegramParserError):
    """Raised when the channel username is invalid or does not exist."""


class TelegramChannelPrivateError(TelegramParserError):
    """Raised when the channel is private or inaccessible."""


class TelegramFloodWaitError(TelegramParserError):
    """Raised when Telegram imposes rate-limiting (FloodWait)."""


class TelegramUnauthorizedError(TelegramParserError):
    """Raised when the Telegram session is not authorized (login required)."""

