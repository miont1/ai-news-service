import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.ai.openai_client import get_openai_client
from app.api.schemas import NewsItemCreate
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RANKER_SYSTEM_PROMPT = (
    "Ти досвідчений шеф-редактор провідного українського новинного медіа. "
    "Твоє завдання — проаналізувати список новин (заголовки та короткий зміст) "
    "та оцінити кожну новину за шкалою від 1.0 до 10.0 за критеріями актуальності, "
    "суспільної ваги та важливості прямо зараз.\n\n"
    "Критерії оцінювання:\n"
    "1. Терміновість та актуальність: ключові події, що відбуваються просто зараз "
    "(breaking news, війна, фронт, дипломатія, важливі заяви та міжнародні рішення).\n"
    "2. Масштаб впливу: події загальнонаціонального або глобального значення "
    "(політика, економіка, безпека, законодавство, допомога партнерам).\n"
    "3. Інновації та технології: помітні досягнення у сфері ШІ, технологій або оборонпрому.\n"
    "4. Штрафи та низькі бали (1.0 - 4.0): дрібний локальний кримінал, побутові події, "
    "плітки, клікбейт, другорядні чи застарілі заяви.\n\n"
    "Формат відповіді:\n"
    "Поверни суворий JSON-об'єкт із масивом 'ranked_news', де кожен елемент містить:\n"
    "- 'index': ціле число (індекс новини із запиту: 0, 1, 2...)\n"
    "- 'score': оцінка від 1.0 до 10.0 (число з плаваючою крапкою)\n"
    "- 'reason': короткий коментар (1 речення), чому новина важлива або другорядна.\n\n"
    "Приклад JSON:\n"
    "{\n"
    '    "ranked_news": [\n'
    '        {"index": 0, "score": 9.5, "reason": "Ключове рішення міжнародних партнерів щодо військової допомоги"},\n'
    '        {"index": 1, "score": 3.0, "reason": "Локальна ДТП без суспільного значення"}\n'
    "    ]\n"
    "}"
)


class AINewsRanker:
    """Service for ranking and selecting top breaking news items using an LLM."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ):
        self.client = client or get_openai_client()
        self.model = model or settings.OPENAI_MODEL
        self.system_prompt = system_prompt or DEFAULT_RANKER_SYSTEM_PROMPT

    def _build_user_message(self, items: list[NewsItemCreate]) -> str:
        """Format candidate news items into a concise numbered list for the prompt."""
        lines = ["Список новин для аналізу та оцінювання:"]
        for idx, item in enumerate(items):
            title = (item.title or "").strip() or "(Без заголовка)"
            # Shorten summary to avoid excessive token consumption
            summary = (item.summary or "").strip()[:300]
            lines.append(f"\n[Новина #{idx}]")
            lines.append(f"Заголовок: {title}")
            if summary:
                lines.append(f"Опис: {summary}")
        return "\n".join(lines)

    def _parse_evaluations(self, response_text: str, total_count: int) -> dict[int, dict[str, Any]]:
        """Safely parse JSON response from LLM to extract {index: {'score': float, 'reason': str}} mapping."""
        cleaned = response_text.strip()
        # Strip potential markdown formatting ```json ... ```
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback search for JSON object inside output
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                raise ValueError("No valid JSON found in LLM response.")

        ranked_list = data.get("ranked_news") or data.get("news") or []
        evaluations: dict[int, dict[str, Any]] = {}
        for entry in ranked_list:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("index"))
                score = float(entry.get("score"))
                reason = str(entry.get("reason") or "").strip()
                if 0 <= idx < total_count:
                    evaluations[idx] = {
                        "score": score,
                        "reason": reason or None,
                    }
            except (ValueError, TypeError):
                continue

        return evaluations

    async def rank_news(
        self,
        items: list[NewsItemCreate],
        top_k: int = 3,
    ) -> list[NewsItemCreate]:
        """Rank news items with LLM and return the top_k most relevant items with ai_score and ai_reason.

        If items count is <= top_k, returns items as-is without calling LLM.
        If LLM evaluation fails, gracefully falls back to the first top_k items.
        """
        if not items:
            return []
        if len(items) <= top_k:
            return items

        user_message = self._build_user_message(items)

        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 1500,
        }

        is_reasoning_model = any(
            self.model.lower().startswith(prefix)
            for prefix in ("o1", "o3", "gpt-5")
        )
        if is_reasoning_model:
            create_kwargs["reasoning_effort"] = "low"
        else:
            create_kwargs["temperature"] = 0.2

        try:
            response = await self.client.chat.completions.create(**create_kwargs)
            choice = response.choices[0]
            raw_text = choice.message.content or ""
            if not raw_text.strip():
                raise ValueError("AI returned an empty response.")

            evaluations = self._parse_evaluations(raw_text, len(items))
            logger.info("AI scored %s items successfully.", len(evaluations))

            # Sort indices descending by score (default score 5.0 for unscored items)
            ranked_indices = sorted(
                range(len(items)),
                key=lambda i: evaluations.get(i, {}).get("score", 5.0),
                reverse=True,
            )
            top_indices = ranked_indices[:top_k]

            selected_items: list[NewsItemCreate] = []
            for i in top_indices:
                item = items[i]
                eval_data = evaluations.get(i)
                if eval_data:
                    item.ai_score = eval_data["score"]
                    item.ai_reason = eval_data["reason"]
                selected_items.append(item)

            return selected_items

        except Exception as e:
            logger.warning(
                "AI news ranking failed (%s: %s). Soft fallback: selecting first %s items.",
                type(e).__name__,
                e,
                top_k,
            )
            return items[:top_k]
