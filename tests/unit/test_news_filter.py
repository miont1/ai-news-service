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
        title="Новий прорив у сфері AI для медицини",
        summary="Компанія представила оновлену версію моделі",
    )
    assert is_news_relevant(item, ["AI"]) is True


def test_is_news_relevant_matches_summary():
    item = create_sample_item(
        title="Новини технологій",
        summary="OpenAI випустила нову версію своєї моделі",
    )
    assert is_news_relevant(item, ["OpenAI"]) is True


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
    assert is_news_relevant(item, None) is True


def test_is_news_relevant_whitespace_or_empty_keywords_do_not_match():
    item = create_sample_item(
        title="Будь-який текст новини",
        summary="Довільний опис",
    )
    # Passing empty strings or whitespace-only keywords must NOT match everything
    assert is_news_relevant(item, ["", "   "]) is False
    assert filter_relevant_news([item], ["", "   "]) == []


def test_is_news_relevant_word_boundaries_prevent_false_positives():
    # Keyword 'AI' must NOT match 'Ukraine', 'email', 'train', 'rain'
    item_ukraine = create_sample_item(title="Ukraine updates export strategy", summary="Economic review")
    item_email = create_sample_item(title="Check your email for details", summary="Communication tips")
    item_train = create_sample_item(title="Speed train arrival", summary="Railway news")
    item_rain = create_sample_item(title="Heavy rain in the region", summary="Weather warning")

    assert is_news_relevant(item_ukraine, ["AI"]) is False
    assert is_news_relevant(item_email, ["AI"]) is False
    assert is_news_relevant(item_train, ["AI"]) is False
    assert is_news_relevant(item_rain, ["AI"]) is False

    # But it MUST match real occurrences with punctuation or standalone words
    item_real_ai = create_sample_item(title="The future of (AI) in 2026", summary="Generative AI adoption")
    assert is_news_relevant(item_real_ai, ["AI"]) is True


def test_is_news_relevant_empty_title_and_summary_handled_safely():
    item_empty = create_sample_item(title="", summary="")
    assert is_news_relevant(item_empty, ["AI"]) is False
    assert is_news_relevant(item_empty, []) is True


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
