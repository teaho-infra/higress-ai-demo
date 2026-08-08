package com.example.aicuration.agent;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

/**
 * Main ReAct-style agent. Orchestrates:
 *  1. RSS sub-agent (uses search_rss MCP tool)
 *  2. SummarizeArticles skill (local, pure)
 *  3. BuildDigestMarkdown skill (local, pure)
 *  4. Notifier sub-agent (uses send_echo MCP tool)
 *
 * <p>Tools wired via Spring AI 2.0 ChatClient.Builder:
 *  - defaultTools(...) accepts the @Tool-annotated SubAgentTools bean
 *  - defaultToolCallbacks(ToolCallbackProvider) accepts the MCP provider
 *  - ToolCallingAdvisor is auto-registered by the chat client when tools
 *    are present, so the agentic tool-call loop is handled for us.
 */
@Service
public class MainReActAgent {

    private final ChatClient chatClient;

    public MainReActAgent(
        ChatClient.Builder chatClientBuilder,
        ToolCallbackProvider toolCallbackProvider,
        AgentWiring.SubAgentTools subAgentTools
    ) {
        this.chatClient = chatClientBuilder
            .defaultToolCallbacks(toolCallbackProvider)
            .defaultTools(subAgentTools)
            .build();
    }

    public String run(String sinceIso, String query, int maxItems) {
        String since = (sinceIso == null || sinceIso.isBlank())
            ? Instant.now().minusSeconds(86_400).atOffset(ZoneOffset.UTC)
                .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
            : sinceIso;
        String q = query == null ? "" : query;

        String userPrompt = String.format(
            "Build today's AI daily digest. since_iso=%s, query=%s, max_items=%d. "
                + "Follow this exact 4-step plan:\n"
                + "  1. Call runRssSearcher to get a JSON list of recent articles.\n"
                + "  2. Call summarizeArticles to condense the list to a markdown bullet list.\n"
                + "  3. Call buildDigestMarkdown to wrap it in a full markdown document.\n"
                + "  4. Call runNotifier to deliver the final document via the echo server.\n"
                + "Return a one-line summary of what was delivered.",
            since, q.isBlank() ? "<empty>" : q, maxItems
        );

        return chatClient.prompt()
            .system("""
                You are a daily-digest orchestrator. Use the provided tools in the
                specified order. Be concise: do not paraphrase the tool outputs back
                to yourself. The pipeline is complete only when the notifier
                sub-agent reports OK from the echo server.
                """)
            .user(userPrompt)
            .call()
            .content();
    }
}
