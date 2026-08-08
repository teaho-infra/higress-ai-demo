package com.example.aicuration.agent;

import com.example.aicuration.skills.SummarizeArticles;
import com.example.aicuration.skills.BuildDigestMarkdown;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Component;

/**
 * Sub-agent that, when invoked, asks the LLM to call the rss-fetcher
 * {@code search_rss} MCP tool and returns the raw JSON list as a String.
 *
 * <p>The sub-agent's tools are restricted to just the two RSS tools, so the
 * LLM cannot accidentally call summarize/build/notify from this sub-agent.
 */
@Component
public class SubAgentRssSearcher {

    private final ChatClient chatClient;
    private final SummarizeArticles summarize;
    private final BuildDigestMarkdown build;

    public SubAgentRssSearcher(
        ChatClient chatClient,
        SummarizeArticles summarize,
        BuildDigestMarkdown build
    ) {
        this.chatClient = chatClient;
        this.summarize = summarize;
        this.build = build;
    }

    public String run(String sinceIso, String query, int maxItems) {
        String userPrompt = String.format(
            "Find recent AI news. since_iso=%s, query=%s, max_items=%d. "
                + "Use the search_rss tool, then return ONLY the raw JSON list "
                + "of articles (no commentary).",
            sinceIso, query.isBlank() ? "<empty>" : query, maxItems
        );
        return chatClient.prompt()
            .system("""
                You are an RSS research sub-agent. You MUST use the search_rss tool
                to fetch articles. Do not invent articles. After the tool returns,
                output the raw JSON list verbatim. If the tool returns an error
                string, return it as-is.
                """)
            .user(userPrompt)
            .call()
            .content();
    }
}
