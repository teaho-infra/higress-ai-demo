"""notifier MCP server (mcp SDK 2.0.0 — high-level MCPServer decorator API).

Exposes two webhook tools:
- send_webhook(url, body_md, title=""): POST markdown to any HTTP endpoint
- send_echo(body_md, title=""): POST to the configured local echo server
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.stdio import stdio_server

ECHO_SERVER_URL = os.environ.get("ECHO_SERVER_URL", "http://localhost:9999/echo")

app = MCPServer("notifier")


async def _post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}


@app.tool()
async def send_webhook(url: str, body_md: str, title: str = "") -> str:
    """POST markdown text to any HTTP webhook URL.

    Returns a string describing the response (parsed JSON if possible, else raw text).
    """
    try:
        payload = {"title": title, "body_md": body_md, "source": "notifier-mcp"}
        result = await _post_json(url, payload)
        return f"OK: {result}"
    except httpx.HTTPError as e:
        return f"ERROR: HTTP failure: {e!r}"
    except Exception as e:
        return f"ERROR: {e!r}"


@app.tool()
async def send_echo(body_md: str, title: str = "") -> str:
    """POST markdown to the configured local echo server.

    Used in this demo to verify the notification pipeline end-to-end.
    """
    try:
        payload = {"title": title, "body_md": body_md, "source": "notifier-mcp"}
        result = await _post_json(ECHO_SERVER_URL, payload)
        return f"OK: {result}"
    except httpx.HTTPError as e:
        return f"ERROR: HTTP failure: {e!r}"
    except Exception as e:
        return f"ERROR: {e!r}"


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
