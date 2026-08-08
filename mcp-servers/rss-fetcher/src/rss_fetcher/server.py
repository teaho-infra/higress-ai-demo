"""rss-fetcher MCP server.

Exposes two tools over the Model Context Protocol:
- list_feeds(): returns the configured RSS feed list
- search_rss(query, since_iso, max_items=20): searches recent articles matching query
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
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

# Default feeds — all about AI / ML / data
DEFAULT_FEEDS: list[dict[str, str]] = [
    {"name": "Hacker News (front page)", "url": "https://hnrss.org/frontpage"},
    {"name": "Hacker News (best)", "url": "https://hnrss.org/best"},
    {"name": "The Decoder", "url": "https://the-decoder.com/feed/"},
    {"name": "MIT News - AI", "url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml"},
]

app = Server("rss-fetcher")


def _parse_date(entry: Any) -> str | None:
    """Extract published date as ISO-8601 string from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed"):
        tt = entry.get(key)
        if tt:
            try:
                return datetime(*tt[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
        except Exception:
            return None
    return None


async def _fetch(url: str, timeout: float = 15.0) -> str:
    """Fetch URL body as text using httpx (async)."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "rss-fetcher-mcp/0.1"})
        r.raise_for_status()
        return r.text


# ----------------------------- tools/list ------------------------------------

async def _list_tools(req: ListToolsRequest) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="list_feeds",
                description="List the configured RSS feeds (name + url). No parameters.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="search_rss",
                description=(
                    "Fetch recent RSS entries from the configured feeds. "
                    "Returns a list of articles (title, url, source, published_at, snippet) "
                    "published at or after `since_iso` (ISO-8601 string). "
                    "Optionally filter by a `query` substring in the title/summary. "
                    "`max_items` caps the total returned (default 20)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Substring to match in title or summary (case-insensitive)."},
                        "since_iso": {
                            "type": "string",
                            "description": "ISO-8601 datetime; only entries at or after this time are returned.",
                        },
                        "max_items": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                    },
                    "required": ["since_iso"],
                },
            ),
        ]
    )


app.add_request_handler("tools/list", ListToolsRequest, _list_tools)


# ----------------------------- tools/call ------------------------------------

async def _call_tool(req: CallToolRequest) -> CallToolResult:
    name = req.params.name
    arguments = req.params.arguments or {}

    if name == "list_feeds":
        return CallToolResult(
            content=[TextContent(type="text", text=str(DEFAULT_FEEDS))],
            is_error=False,
        )

    if name == "search_rss":
        query = (arguments.get("query") or "").lower()
        since_iso = arguments.get("since_iso")
        max_items = int(arguments.get("max_items", 20))

        if not since_iso:
            return CallToolResult(
                content=[TextContent(type="text", text="ERROR: since_iso is required")],
                is_error=True,
            )

        try:
            since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        except ValueError as e:
            return CallToolResult(
                content=[TextContent(type="text", text=f"ERROR: invalid since_iso: {e}")],
                is_error=True,
            )

        articles: list[dict[str, Any]] = []
        for feed in DEFAULT_FEEDS:
            try:
                body = await _fetch(feed["url"])
            except Exception as e:
                articles.append({"source": feed["name"], "error": f"fetch failed: {e!r}"})
                continue
            parsed = feedparser.parse(body)
            for entry in parsed.entries:
                published_iso = _parse_date(entry)
                if not published_iso:
                    continue
                try:
                    pub_dt = datetime.fromisoformat(published_iso)
                except ValueError:
                    continue
                if pub_dt < since_dt:
                    continue
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                if query and query not in title.lower() and query not in summary.lower():
                    continue
                articles.append({
                    "title": title,
                    "url": entry.get("link", ""),
                    "source": feed["name"],
                    "published_at": published_iso,
                    "snippet": summary[:280] if summary else "",
                })
                if len(articles) >= max_items:
                    break
            if len(articles) >= max_items:
                break

        return CallToolResult(
            content=[TextContent(type="text", text=str(articles))],
            is_error=False,
        )

    return CallToolResult(
        content=[TextContent(type="text", text=f"ERROR: unknown tool {name!r}")],
        is_error=True,
    )


app.add_request_handler("tools/call", CallToolRequest, _call_tool)


# ----------------------------- main ------------------------------------------

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
