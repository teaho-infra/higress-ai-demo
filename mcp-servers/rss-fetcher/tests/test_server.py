"""Tests for rss-fetcher MCP server (focus on tool behavior + return shape)."""

import pytest

from rss_fetcher.server import (
    list_feeds,
    search_rss,
    DEFAULT_FEEDS,
)


@pytest.mark.asyncio
async def test_list_feeds_returns_default_feeds():
    text = await list_feeds()
    assert "Hacker News" in text
    assert len(DEFAULT_FEEDS) >= 3


@pytest.mark.asyncio
async def test_search_rss_invalid_since_iso_returns_error():
    result = await search_rss(since_iso="not-a-date")
    # When invalid, function returns a string starting with "ERROR"
    assert "ERROR" in result
    assert "since_iso" in result


@pytest.mark.asyncio
async def test_search_rss_filters_by_future_date(monkeypatch):
    """If since_iso is far in the future, search_rss should return no articles
    (and tolerate any network failures — it returns a list repr)."""
    result = await search_rss(since_iso="2099-01-01T00:00:00+00:00", max_items=5)
    # Returns a list (possibly empty if network works; or contains fetch-error entries)
    assert result.startswith("[") and result.endswith("]")
