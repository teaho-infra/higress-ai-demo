package com.example.aicuration.agent;

import com.example.aicuration.skills.SummarizeArticles;
import com.example.aicuration.skills.BuildDigestMarkdown;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires the two sub-agents as @Tool methods on the main agent's chat client.
 *
 * <p>The main ReAct agent sees these as plain local tools alongside the
 * MCP tools and the @Tool skills (SummarizeArticles, BuildDigestMarkdown).
 * The ToolCallingAdvisor handles the tool-call loop automatically.
 */
@Configuration
public class AgentWiring {

    @Bean
    public SubAgentTools subAgentTools(SubAgentRssSearcher searcher, SubAgentNotifier notifier) {
        return new SubAgentTools(searcher, notifier);
    }

    /**
     * Holder bean exposing the sub-agents as @Tool methods. The main agent's
     * tool callbacks include these methods.
     */
    public static class SubAgentTools {

        private final SubAgentRssSearcher searcher;
        private final SubAgentNotifier notifier;

        SubAgentTools(SubAgentRssSearcher searcher, SubAgentNotifier notifier) {
            this.searcher = searcher;
            this.notifier = notifier;
        }

        @Tool(description = """
            Run the RSS research sub-agent. It uses the rss-fetcher MCP tool
            (search_rss) and returns the raw JSON list of articles. Use this
            FIRST in the digest pipeline.
            """)
        public String runRssSearcher(
            @ToolParam(description = "ISO-8601 datetime; only articles at or after this are returned.")
            String sinceIso,
            @ToolParam(description = "Optional search query substring. Empty for no query filter.")
            String query,
            @ToolParam(description = "Max articles to return. Default 20.")
            Integer maxItems
        ) {
            return searcher.run(sinceIso, query == null ? "" : query, maxItems == null ? 20 : maxItems);
        }

        @Tool(description = """
            Run the notification sub-agent. It uses the notifier MCP tool
            (send_echo) to POST the digest to the local echo server. Use this
            LAST in the digest pipeline.
            """)
        public String runNotifier(
            @ToolParam(description = "The full digest markdown document to send.")
            String bodyMd,
            @ToolParam(description = "Title for the notification. Default: 'AI Daily Digest'.")
            String title
        ) {
            return notifier.run(bodyMd, title == null || title.isBlank() ? "AI Daily Digest" : title);
        }
    }
}
