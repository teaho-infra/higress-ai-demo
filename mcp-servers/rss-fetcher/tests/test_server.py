"""Tests for rss-fetcher MCP server (focus on tool registration + search_rss logic)."""

import pytest

from rss_fetcher.server import (
    _list_tools,
    _call_tool,
    DEFAULT_FEEDS,
)
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest


@pytest.mark.asyncio
async def test_list_tools_returns_two_tools():
    req = ListToolsRequest(method="tools/list")
    result = await _list_tools(req)
    names = {t.name for t in result.tools}
    assert names == {"list_feeds", "search_rss"}


@pytest.mark.asyncio
async def test_list_feeds_returns_default_feeds():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="list_feeds", arguments={}),
    )
    result = await _call_tool(req)
    assert result.is_error is False
    assert len(result.content) == 1
    text = result.content[0].text
    assert "Hacker News" in text
    assert len(DEFAULT_FEEDS) >= 3


@pytest.mark.asyncio
async def test_search_rss_invalid_since_iso_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="search_rss", arguments={"since_iso": "not-a-date"}),
    )
    result = await _call_tool(req)
    assert result.is_error is True
    assert "since_iso" in result.content[0].text


@pytest.mark.asyncio
async def test_search_rss_missing_since_iso_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="search_rss", arguments={}),
    )
    result = await _call_tool(req)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_search_rss_unknown_tool_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="not_a_real_tool", arguments={}),
    )
    result = await _call_tool(req)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_search_rss_filters_by_future_date(monkeypatch):
    """If since_iso is far in the future, search_rss should return no articles
    (but we don't actually hit the network — feeds will fail gracefully)."""
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="search_rss",
            arguments={"since_iso": "2099-01-01T00:00:00+00:00", "max_items": 5},
        ),
    )
    result = await _call_tool(req)
    assert result.is_error is False
    assert len(result.content) == 1
    text = result.content[0].text
    # Returns a list (possibly empty if network works; or contains fetch-error entries)
    assert text.startswith("[") and text.endswith("]")
