from app.api.schemas import NewsItemCreate


def is_news_relevant(item: NewsItemCreate, keywords: list[str]) -> bool:
    """
    Checks if a news item contains any of the given keywords in title or summary.
    If keywords list is empty, returns True (no filtering configured).
    """
    if not keywords:
        return True

    text_to_check = f"{item.title} {item.summary}".lower()
    return any(keyword.lower() in text_to_check for keyword in keywords)


def filter_relevant_news(items: list[NewsItemCreate], keywords: list[str]) -> list[NewsItemCreate]:
    """
    Filters out news items that don't match any keyword in title or summary.
    """
    if not keywords:
        return items

    return [item for item in items if is_news_relevant(item, keywords)]
