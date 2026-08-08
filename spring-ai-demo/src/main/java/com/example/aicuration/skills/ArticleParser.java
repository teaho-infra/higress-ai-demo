package com.example.aicuration.skills;

import com.example.aicuration.domain.Article;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Collections;
import java.util.List;

/**
 * Tiny helper to parse the JSON array string that the rss-fetcher MCP tool
 * returns. Kept package-private on purpose — used by skills + tests.
 */
final class ArticleParser {
    private static final ObjectMapper MAPPER = new ObjectMapper()
        .findAndRegisterModules();  // picks up JavaTimeModule for Instant

    private ArticleParser() {}

    static List<Article> parseList(String json) {
        if (json == null || json.isBlank()) {
            return Collections.emptyList();
        }
        String trimmed = json.trim();
        try {
            return MAPPER.readValue(trimmed, new TypeReference<List<Article>>() {});
        } catch (Exception e) {
            // Treat as plain text error from MCP tool, e.g. starts with "ERROR:"
            return Collections.emptyList();
        }
    }
}
