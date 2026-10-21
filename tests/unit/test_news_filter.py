from datetime import UTC, datetime

from app.api.schemas import NewsItemCreate
from app.services.news_filter import filter_relevant_news, is_news_relevant


def create_sample_item(title: str, summary: str, url: str = "https://example.com/1") -> NewsItemCreate:
    return NewsItemCreate(
        title=title,
        summary=summary,
        url=url,
        source="https://example.com/rss",
        published_at=datetime.now(UTC),
    )


def test_is_news_relevant_matches_title():
    item = create_sample_item(
        title="Новий прорив у штучному інтелекті",
        summary="Компанія представила оновлену версію моделі",
    )
    assert is_news_relevant(item, ["інтелект"]) is True


def test_is_news_relevant_matches_summary():
    item = create_sample_item(
        title="Новини технологій",
        summary="OpenAI випустила нову версію своєї моделі",
    )
    assert is_news_relevant(item, ["openai"]) is True


def test_is_news_relevant_case_insensitive():
    item = create_sample_item(
        title="UKRAINE WINS TECH AWARD",
        summary="A major announcement from Kyiv",
    )
    assert is_news_relevant(item, ["ukraine"]) is True
    assert is_news_relevant(item, ["kyiv"]) is True


def test_is_news_relevant_no_match():
    item = create_sample_item(
        title="Кулінарні рецепти на вихідні",
        summary="Як приготувати смачний яблучний пиріг",
    )
    assert is_news_relevant(item, ["технології", "AI", "Python"]) is False


def test_is_news_relevant_empty_keywords_allows_all():
    item = create_sample_item(
        title="Будь-яка новина",
        summary="Опис без обмежень",
    )
    assert is_news_relevant(item, []) is True


def test_filter_relevant_news_filters_batch():
    item_relevant_1 = create_sample_item(title="AI перевершує очікування", summary="Тест", url="https://ex.com/1")
    item_irrelevant = create_sample_item(title="Погода на завтра", summary="Дощ", url="https://ex.com/2")
    item_relevant_2 = create_sample_item(title="Технологічний дайджест", summary="Огляд LLM моделей", url="https://ex.com/3")

    items = [item_relevant_1, item_irrelevant, item_relevant_2]
    keywords = ["AI", "LLM"]

    filtered = filter_relevant_news(items, keywords)
    assert len(filtered) == 2
    assert item_relevant_1 in filtered
    assert item_relevant_2 in filtered
    assert item_irrelevant not in filtered
