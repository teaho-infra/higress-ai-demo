package com.example.aicuration.skills;

import com.example.aicuration.domain.Article;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Pure, deterministic local skill: collapse a list of RSS articles into a
 * compact summary that preserves provenance (source + url) per item.
 *
 * <p>No LLM call inside this skill — it's deliberately a pure function so
 * the LLM-driven agent can call it without making the pipeline non-deterministic
 * at this step.
 */
@Component
public class SummarizeArticles {

    @Tool(description = """
        Summarize a list of articles into a compact markdown bullet list.
        Each bullet preserves the title, source, and URL so readers can
        click through. Sorts by publishedAt descending (newest first) and
        caps the number of items returned.
        """)
    public String summarize(
        @ToolParam(description = "Articles to summarize, as a JSON array string "
            + "matching the shape returned by the rss-fetcher search_rss tool.")
        String articlesJson,
        @ToolParam(description = "Maximum number of items in the summary. Default 10.")
        Integer maxItems
    ) {
        int cap = (maxItems == null || maxItems <= 0) ? 10 : maxItems;
        List<Article> articles = ArticleParser.parseList(articlesJson);
        if (articles.isEmpty()) {
            return "_(no articles found)_";
        }
        List<Article> sorted = new ArrayList<>(articles);
        sorted.sort(Comparator.comparing(
            Article::publishedAt,
            Comparator.nullsLast(Comparator.reverseOrder())
        ));
        if (sorted.size() > cap) {
            sorted = sorted.subList(0, cap);
        }
        StringBuilder sb = new StringBuilder();
        for (Article a : sorted) {
            sb.append("- [")
              .append(escapeBrackets(a.title()))
              .append("](")
              .append(a.url())
              .append(") _")
              .append(a.source())
              .append("_");
            if (a.publishedAt() != null) {
                sb.append(" (").append(a.publishedAt().toString().substring(0, 10)).append(")");
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    private static String escapeBrackets(String s) {
        return s.replace("[", "\\[").replace("]", "\\]");
    }
}
