class AIGenerationError(Exception):
    """Base exception for AI post generation failures."""


class AIRateLimitError(AIGenerationError):
    """Raised when the AI provider rate limit is exceeded."""


class AIServiceUnavailableError(AIGenerationError):
    """Raised when the AI provider is unreachable or times out."""


class AIAuthenticationError(AIGenerationError):
    """Raised when API key is missing or invalid."""
