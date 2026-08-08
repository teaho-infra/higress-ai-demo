"""rss-fetcher MCP server (mcp SDK 2.0.0 — high-level MCPServer with decorator API).

Exposes two tools:
- list_feeds(): returns the configured RSS feed list
- search_rss(since_iso, query=None, max_items=20): searches recent articles matching query
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from mcp.server import MCPServer
from mcp.server.stdio import stdio_server

# Default feeds — all about AI / ML / data
DEFAULT_FEEDS: list[dict[str, str]] = [
    {"name": "Hacker News (front page)", "url": "https://hnrss.org/frontpage"},
    {"name": "Hacker News (best)", "url": "https://hnrss.org/best"},
    {"name": "The Decoder", "url": "https://the-decoder.com/feed/"},
    {"name": "MIT News - AI", "url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml"},
]


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


# Module-level server (set up in main)
app = MCPServer("rss-fetcher")


@app.tool()
async def list_feeds() -> str:
    """List the configured RSS feeds (name + url). No parameters.

    Returns a Python repr of the feed list.
    """
    return str(DEFAULT_FEEDS)


@app.tool()
async def search_rss(
    since_iso: str,
    query: str = "",
    max_items: int = 20,
) -> str:
    """Fetch recent RSS entries from the configured feeds.

    Returns a Python repr of a list of articles (title, url, source,
    published_at, snippet) published at or after `since_iso` (ISO-8601
    string). Optionally filter by a `query` substring in the
    title/summary (case-insensitive). `max_items` caps the total
    returned (default 20).
    """
    q = (query or "").lower()
    try:
        since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    except ValueError as e:
        return f"ERROR: invalid since_iso: {e}"

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
            if q and q not in title.lower() and q not in summary.lower():
                continue
            articles.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": feed["name"],
                "published_at": published_iso,
                "snippet": summary[:280] if summary else "",
            })
            if len(articles) >= max_items:
                return str(articles)
    return str(articles)


# mcp SDK 2.0.0 high-level API: MCPServer.run("stdio") handles
# stdio_server() + create_initialization_options() internally.
def main() -> None:
    app.run("stdio")


if __name__ == "__main__":
    main()
