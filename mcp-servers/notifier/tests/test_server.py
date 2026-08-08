"""Tests for notifier MCP server (focus on tool behavior + request shape validation)."""

from unittest.mock import patch, AsyncMock

import pytest

from notifier.server import (
    send_webhook,
    send_echo,
    ECHO_SERVER_URL,
)


def _mock_response(json_body: dict):
    r = AsyncMock()
    r.json = lambda: json_body
    r.raise_for_status = lambda: None
    return r


@pytest.mark.asyncio
async def test_send_webhook_missing_url_raises_or_returns_error():
    # In this MCPServer API, type checking happens at the framework level;
    # the function body just executes. Missing required arg => TypeError.
    with pytest.raises(TypeError):
        await send_webhook(body_md="hi")  # no `url`


@pytest.mark.asyncio
async def test_send_echo_missing_body_raises_or_returns_error():
    with pytest.raises(TypeError):
        await send_echo()  # no `body_md`


@pytest.mark.asyncio
async def test_send_webhook_calls_post_with_correct_payload():
    """Mock the HTTP call and verify the URL + body shape."""
    fake_response = _mock_response({"ok": True, "received": True})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("notifier.server.httpx.AsyncClient", return_value=fake_client):
        result = await send_webhook(
            url="http://example.test/hook", body_md="# hi", title="Test"
        )

    assert result.startswith("OK:")
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
    fake_response = _mock_response({"echo": True})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("notifier.server.httpx.AsyncClient", return_value=fake_client):
        result = await send_echo(body_md="**hello**")

    assert result.startswith("OK:")
    fake_client.post.assert_called_once()
    called_url, _ = fake_client.post.call_args
    assert called_url == (ECHO_SERVER_URL,)


@pytest.mark.asyncio
async def test_send_webhook_http_error_returns_error_string():
    import httpx

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("notifier.server.httpx.AsyncClient", return_value=fake_client):
        result = await send_webhook(url="http://x", body_md="y")

    assert "ERROR" in result
