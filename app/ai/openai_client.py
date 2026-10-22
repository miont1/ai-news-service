import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def get_openai_client(
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncOpenAI:
    """Creates and returns an AsyncOpenAI client instance.

    Uses application settings by default if parameters are not explicitly
    provided.
    """
    resolved_api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
    resolved_base_url = base_url if base_url is not None else settings.OPENAI_BASE_URL

    if not resolved_api_key:
        logger.warning(
            "OPENAI_API_KEY is not configured. AI operations will fail unless a valid key is provided."
        )

    return AsyncOpenAI(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        timeout=30.0,
        max_retries=2,
    )
