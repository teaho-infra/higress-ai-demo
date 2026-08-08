"""notifier MCP server.

Exposes two webhook tools over the Model Context Protocol:
- send_webhook(url, body_md, title?): POST markdown to any HTTP endpoint
- send_echo(body_md, title?): POST to the configured local echo server
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
    Tool,
)

ECHO_SERVER_URL = os.environ.get("ECHO_SERVER_URL", "http://localhost:9999/echo")

app = Server("notifier")


async def _post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}


async def _list_tools(req: ListToolsRequest) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="send_webhook",
                description=(
                    "POST markdown text to any HTTP webhook URL. "
                    "Returns the response (parsed JSON if possible, else raw text)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target webhook URL (http/https)."},
                        "body_md": {"type": "string", "description": "Markdown body to send."},
                        "title": {"type": "string", "description": "Optional title / subject."},
                    },
                    "required": ["url", "body_md"],
                },
            ),
            Tool(
                name="send_echo",
                description=(
                    f"POST markdown to the configured local echo server at {ECHO_SERVER_URL}. "
                    "Used in this demo to verify the notification pipeline end-to-end."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "body_md": {"type": "string", "description": "Markdown body to send."},
                        "title": {"type": "string", "description": "Optional title / subject."},
                    },
                    "required": ["body_md"],
                },
            ),
        ]
    )


app.add_request_handler("tools/list", ListToolsRequest, _list_tools)


async def _call_tool(req: CallToolRequest) -> CallToolResult:
    name = req.params.name
    arguments = req.params.arguments or {}

    try:
        if name == "send_webhook":
            url = arguments.get("url")
            body_md = arguments.get("body_md")
            title = arguments.get("title", "")
            if not url or not body_md:
                return CallToolResult(
                    content=[TextContent(type="text", text="ERROR: url and body_md are required")],
                    is_error=True,
                )
            payload = {"title": title, "body_md": body_md, "source": "notifier-mcp"}
            result = await _post_json(url, payload)
            return CallToolResult(
                content=[TextContent(type="text", text=f"OK: {result}")],
                is_error=False,
            )

        if name == "send_echo":
            body_md = arguments.get("body_md")
            title = arguments.get("title", "")
            if not body_md:
                return CallToolResult(
                    content=[TextContent(type="text", text="ERROR: body_md is required")],
                    is_error=True,
                )
            payload = {"title": title, "body_md": body_md, "source": "notifier-mcp"}
            result = await _post_json(ECHO_SERVER_URL, payload)
            return CallToolResult(
                content=[TextContent(type="text", text=f"OK: {result}")],
                is_error=False,
            )

        return CallToolResult(
            content=[TextContent(type="text", text=f"ERROR: unknown tool {name!r}")],
            is_error=True,
        )
    except httpx.HTTPError as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"ERROR: HTTP failure: {e!r}")],
            is_error=True,
        )
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"ERROR: {e!r}")],
            is_error=True,
        )


app.add_request_handler("tools/call", CallToolRequest, _call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
