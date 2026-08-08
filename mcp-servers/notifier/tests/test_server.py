"""Tests for notifier MCP server (focus on tool registration + request shape validation)."""

import json
from unittest.mock import patch, AsyncMock

import pytest

from notifier.server import (
    _list_tools,
    _call_tool,
    ECHO_SERVER_URL,
)
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest


@pytest.mark.asyncio
async def test_list_tools_returns_two_tools():
    req = ListToolsRequest(method="tools/list")
    result = await _list_tools(req)
    names = {t.name for t in result.tools}
    assert names == {"send_webhook", "send_echo"}


@pytest.mark.asyncio
async def test_send_webhook_missing_url_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="send_webhook", arguments={"body_md": "hi"}),
    )
    result = await _call_tool(req)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_send_webhook_missing_body_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="send_webhook", arguments={"url": "http://x"}),
    )
    result = await _call_tool(req)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_send_echo_missing_body_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="send_echo", arguments={}),
    )
    result = await _call_tool(req)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_send_webhook_calls_post_with_correct_payload():
    """Mock the HTTP call and verify the URL + body shape."""
    fake_response = AsyncMock()
    fake_response.json = lambda: {"ok": True, "received": True}
    fake_response.raise_for_status = lambda: None

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("notifier.server.httpx.AsyncClient", return_value=fake_client):
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="send_webhook",
                arguments={"url": "http://example.test/hook", "body_md": "# hi", "title": "Test"},
            ),
        )
        result = await _call_tool(req)

    assert result.is_error is False
    # Verify post was called once with correct URL + JSON payload
    fake_client.post.assert_called_once()
    called_url, called_kwargs = fake_client.post.call_args
    assert called_url == ("http://example.test/hook",)
    assert called_kwargs["json"] == {
        "title": "Test",
        "body_md": "# hi",
        "source": "notifier-mcp",
    }


@pytest.mark.asyncio
async def test_send_echo_uses_configured_echo_url():
    fake_response = AsyncMock()
    fake_response.json = lambda: {"echo": True}
    fake_response.raise_for_status = lambda: None

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("notifier.server.httpx.AsyncClient", return_value=fake_client):
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="send_echo",
                arguments={"body_md": "**hello**"},
            ),
        )
        result = await _call_tool(req)

    assert result.is_error is False
    fake_client.post.assert_called_once()
    called_url, _ = fake_client.post.call_args
    assert called_url == (ECHO_SERVER_URL,)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="not_a_tool", arguments={}),
    )
    result = await _call_tool(req)
    assert result.is_error is True
