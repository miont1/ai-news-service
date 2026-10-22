import logging

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from app.ai.exceptions import (
    AIAuthenticationError,
    AIGenerationError,
    AIRateLimitError,
    AIServiceUnavailableError,
)
from app.ai.openai_client import get_openai_client
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "Ти досвідчений SMM-редактор новинного Telegram-каналу. "
    "Твоє завдання — перетворити надану новину на яскравий, лаконічний та цікавий пост для Telegram.\n\n"
    "Вимоги до поста:\n"
    "1. Заголовок: короткий, чіпляючий, з тематичним емодзі на початку.\n"
    "2. Основна суть: 2-3 лаконічних речення (розкрий головну думку, уникай зайвих деталей та канцеляризмів).\n"
    "3. Заклик до дії (Call to Action / CTA): наприкінці постав коротке запитання для аудиторії або заклик висловити думку в коментарях.\n"
    "4. Джерело: якщо надано URL новини, додай посилання у форматі: '🔗 Детальніше: <url>'.\n"
    "5. Хештеги: наприкінці додай 2-4 доречні хештеги (наприклад: #новини #технології).\n"
    "6. Мова поста: українська.\n"
    "7. Форматування: охайний Telegram Markdown."
)


class PostGenerator:
    """Service for generating Telegram posts using an LLM."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ):
        self.client = client or get_openai_client()
        self.model = model or settings.OPENAI_MODEL
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    def _build_user_message(
        self,
        title: str,
        content: str | None = None,
        summary: str | None = None,
        raw_text: str | None = None,
        source_url: str | None = None,
    ) -> str:
        parts = []
        if title and title.strip():
            parts.append(f"Заголовок новини: {title.strip()}")

        if summary and summary.strip():
            parts.append(f"Короткий зміст (Summary):\n{summary.strip()}")

        if raw_text and raw_text.strip():
            cleaned_raw = raw_text.strip()
            # If raw_text is distinct from summary, append it (truncated to 5000 chars)
            if cleaned_raw != (summary or "").strip():
                parts.append(f"Повний текст статті:\n{cleaned_raw[:5000]}")
        elif content and content.strip():
            # Fallback if raw_text/summary are not provided separately
            cleaned_content = content.strip()
            if cleaned_content != (summary or "").strip():
                parts.append(f"Зміст/Опис новини:\n{cleaned_content[:5000]}")

        if source_url and source_url.strip():
            parts.append(f"Першоджерело: {source_url.strip()}")

        return "\n\n".join(parts)

    async def generate_post(
        self,
        title: str,
        content: str | None = None,
        summary: str | None = None,
        raw_text: str | None = None,
        source_url: str | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        """Generates a Telegram post from article title, summary, and content/raw_text.

        Raises:
            AIAuthenticationError: on invalid or missing API key.
            AIRateLimitError: on HTTP 429 rate limit errors.
            AIServiceUnavailableError: on timeouts and network issues.
            AIGenerationError: on any other API or unexpected error.
        """
        if not title and not content and not summary and not raw_text:
            raise ValueError("Both title and content cannot be empty.")

        cleaned_prompt = custom_prompt.strip() if custom_prompt and custom_prompt.strip() else None
        system_prompt = cleaned_prompt or self.system_prompt
        user_message = self._build_user_message(
            title=title,
            content=content,
            summary=summary,
            raw_text=raw_text,
            source_url=source_url,
        )

        create_kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_completion_tokens": 2000,
        }

        is_reasoning_model = any(
            self.model.lower().startswith(prefix)
            for prefix in ("o1", "o3", "gpt-5")
        )
        if is_reasoning_model:
            create_kwargs["reasoning_effort"] = "low"
        else:
            create_kwargs["temperature"] = 0.7

        try:
            response = await self.client.chat.completions.create(**create_kwargs)

            choice = response.choices[0]
            generated_text = choice.message.content
            if not generated_text:
                if choice.finish_reason == "length":
                    raise AIGenerationError(
                        "AI token limit was exhausted during reasoning before generating text. "
                        "Consider increasing token budget or setting lower reasoning effort."
                    )
                raise AIGenerationError("AI returned an empty response.")

            return generated_text.strip()

        except AuthenticationError as e:
            logger.error("AI authentication failed: %s", e)
            raise AIAuthenticationError(f"OpenAI authentication error: {e}") from e

        except RateLimitError as e:
            logger.error("AI rate limit reached: %s", e)
            raise AIRateLimitError(f"OpenAI rate limit exceeded: {e}") from e

        except (APIConnectionError, APITimeoutError) as e:
            logger.error("AI service connection failed: %s", e)
            raise AIServiceUnavailableError(
                f"OpenAI service unavailable: {e}"
            ) from e

        except APIStatusError as e:
            logger.error("AI status error (%s): %s", e.status_code, e)
            raise AIGenerationError(
                f"OpenAI status error ({e.status_code}): {e.message}"
            ) from e

        except OpenAIError as e:
            logger.error("OpenAI API error: %s", e)
            raise AIGenerationError(f"OpenAI error: {e}") from e

        except Exception as e:
            if isinstance(e, AIGenerationError):
                raise
            logger.error("Unexpected error in post generation: %s", e)
            raise AIGenerationError(f"Failed to generate post: {e}") from e
