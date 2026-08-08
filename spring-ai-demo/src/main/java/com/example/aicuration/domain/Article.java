package com.example.aicuration.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;

/**
 * A single news article surfaced by the rss-fetcher MCP tool.
 *
 * <p>Mirrors the dict shape that {@code search_rss} returns from the Python
 * server: title, url, source, published_at (ISO-8601), snippet.
 */
public record Article(
    String title,
    String url,
    String source,
    @JsonProperty("published_at") Instant publishedAt,
    String snippet
) {
    public Article {
        if (title == null || title.isBlank()) {
            throw new IllegalArgumentException("title is required");
        }
        if (url == null || url.isBlank()) {
            throw new IllegalArgumentException("url is required");
        }
        if (source == null || source.isBlank()) {
            throw new IllegalArgumentException("source is required");
        }
    }
}
