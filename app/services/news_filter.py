import re

from app.api.schemas import NewsItemCreate


def is_news_relevant(item: NewsItemCreate, keywords: list[str]) -> bool:
    """
    Checks if a news item contains any of the given keywords in title or summary.
    - If keywords is empty/None, returns True (no filtering configured).
    - If keywords contains only empty/whitespace strings, returns False (invalid filter).
    - Uses Unicode-aware word boundaries to prevent false positive substring matches
      (e.g., 'AI' won't match 'Ukraine', 'email', or 'train').
    - Safely handles empty title or summary.
    """
    if keywords is None:
        return True

    cleaned_keywords = [k.strip() for k in keywords if k and k.strip()]
    if not cleaned_keywords:
        # If caller passed non-empty list like ["", "   "], do not match all text
        return len(keywords) == 0

    title = item.title or ""
    summary = item.summary or ""
    text_to_check = f"{title} {summary}"
    if not text_to_check.strip():
        return False

    for keyword in cleaned_keywords:
        pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
        if re.search(pattern, text_to_check, flags=re.IGNORECASE | re.UNICODE):
            return True

    return False


def filter_relevant_news(items: list[NewsItemCreate], keywords: list[str]) -> list[NewsItemCreate]:
    """
    Filters out news items that don't match any keyword in title or summary.
    """
    if keywords is None or len(keywords) == 0:
        return items

    cleaned_keywords = [k.strip() for k in keywords if k and k.strip()]
    if not cleaned_keywords:
        return []

    return [item for item in items if is_news_relevant(item, keywords)]

