from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from selectolax.lexbor import LexborHTMLParser

from app.news_parser.sites import fetch_raw_text, fetch_rss_feed, parse_rss_item


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


def test_parse_rss_item_atom_style_link_href():
    rss_snippet = """
    <item>
        <title>Новина в Atom стилі</title>
        <link href="https://example.com/atom-article" rel="alternate"/>
        <description>Опис</description>
    </item>
    """
    tree = LexborHTMLParser(rss_snippet)
    item_node = tree.css_first("item")

    result = parse_rss_item(item_node, "https://example.com/rss")
    assert result.url == "https://example.com/atom-article"


def test_parse_rss_item_missing_guid_and_link():
    rss_snippet = """
    <item>
        <title>Новина без посилань</title>
        <description>Тільки опис</description>
    </item>
    """
    tree = LexborHTMLParser(rss_snippet)
    item_node = tree.css_first("item")

    result = parse_rss_item(item_node, "https://example.com/rss")
    assert result.url == ""
    assert result.title == "Новина без посилань"


def test_parse_rss_item_invalid_and_missing_pub_date():
    # 1. Invalid date string
    snippet_invalid_date = """
    <item>
        <title>Новина</title>
        <pubDate>Invalid Date String 99999</pubDate>
    </item>
    """
    tree1 = LexborHTMLParser(snippet_invalid_date)
    before_1 = datetime.now(UTC)
    res1 = parse_rss_item(tree1.css_first("item"), "https://example.com/rss")
    after_1 = datetime.now(UTC)
    assert before_1 <= res1.published_at <= after_1

    # 2. Missing pubDate tag
    snippet_no_date = """
    <item>
        <title>Новина без дати</title>
    </item>
    """
    tree2 = LexborHTMLParser(snippet_no_date)
    before_2 = datetime.now(UTC)
    res2 = parse_rss_item(tree2.css_first("item"), "https://example.com/rss")
    after_2 = datetime.now(UTC)
    assert before_2 <= res2.published_at <= after_2


@pytest.mark.asyncio
async def test_fetch_rss_feed_handles_network_errors_gracefully():
    # 1. HTTP 404 / 500 error
    mock_response_500 = httpx.Response(status_code=500, request=httpx.Request("GET", "https://error.com/rss"))
    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.HTTPStatusError("Server Error", request=mock_response_500.request, response=mock_response_500))):
        items = await fetch_rss_feed("https://error.com/rss")
        assert items == []

    # 2. Timeout error
    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectTimeout("Connection timed out"))):
        items = await fetch_rss_feed("https://timeout.com/rss")
        assert items == []


@pytest.mark.asyncio
async def test_fetch_raw_text_handles_network_errors():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # 1. Empty URL
    assert await fetch_raw_text(mock_client, "") == ""

    # 2. HTTP error during text extraction
    mock_client.get.side_effect = httpx.HTTPError("Network failure")
    assert await fetch_raw_text(mock_client, "https://example.com/article") == ""
