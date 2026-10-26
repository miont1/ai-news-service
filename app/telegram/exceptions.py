class TelegramPublishError(Exception):
    """Base exception for Telegram publishing errors."""


class PostNotFoundError(TelegramPublishError):
    """Raised when the post to be published does not exist."""


class PostAlreadyPublishedError(TelegramPublishError):
    """Raised when trying to publish a post that is already published."""


class PostPublishingInProgressError(TelegramPublishError):
    """Raised when trying to publish a post that is currently in PUBLISHING status."""


class TelegramChannelValidationError(TelegramPublishError):
    """Raised when the target channel is missing or not configured."""


class TelegramPublishForbiddenError(TelegramPublishError):
    """Raised when the bot or user lacks write permissions to the channel."""


class TelegramPublishChannelError(TelegramPublishError):
    """Raised when the target channel is private, invalid, or does not exist."""


class TelegramPublishFloodWaitError(TelegramPublishError):
    """Raised when Telegram rate limits posting (FloodWait)."""

    def __init__(self, message: str, seconds: int = 0):
        super().__init__(message)
        self.seconds = seconds


class TelegramPublishUnauthorizedError(TelegramPublishError):
    """Raised when the Telegram session is not authorized."""
