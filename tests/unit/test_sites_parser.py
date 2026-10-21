from selectolax.lexbor import LexborHTMLParser

from app.news_parser.sites import parse_rss_item


def test_parse_rss_item_success():
    rss_snippet = """
    <item>
        <title>Тестовий заголовок новини</title>
        <guid>https://example.com/news/123</guid>
        <description>Опис важливої події</description>
        <pubDate>Wed, 21 Oct 2026 10:00:00 +0000</pubDate>
    </item>
    """
    tree = LexborHTMLParser(rss_snippet)
    item_node = tree.css_first("item")
    feed_url = "https://example.com/rss.xml"

    result = parse_rss_item(item_node, feed_url)

    assert result.title == "Тестовий заголовок новини"
    assert result.url == "https://example.com/news/123"
    assert result.summary == "Опис важливої події"
    assert result.source == feed_url
    assert result.id is not None  # SHA-256 generated automatically
    assert result.raw_text is None


def test_parse_rss_item_fallback_link_if_no_guid():
    rss_snippet = """
    <item>
        <title>Новина з тегом link</title>
        <link>https://example.com/news/fallback-url</link>
        <description>Опис новини</description>
    </item>
    """
    tree = LexborHTMLParser(rss_snippet)
    item_node = tree.css_first("item")

    result = parse_rss_item(item_node, "https://example.com/rss")

    assert result.url == "https://example.com/news/fallback-url"
    assert result.published_at is not None
