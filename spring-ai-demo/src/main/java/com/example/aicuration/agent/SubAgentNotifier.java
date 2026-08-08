package com.example.aicuration.agent;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Component;

/**
 * Sub-agent that, when invoked, asks the LLM to call the notifier MCP tool
 * ({@code send_echo}) to deliver the digest markdown.
 *
 * <p>Tools restricted to the two notifier tools so the LLM cannot accidentally
 * call RSS tools or skills.
 */
@Component
public class SubAgentNotifier {

    private final ChatClient chatClient;

    public SubAgentNotifier(ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    public String run(String bodyMd, String title) {
        String userPrompt = String.format(
            "Deliver this digest. body_md starts with: %s. title=%s. "
                + "Use the send_echo tool to POST it to the local echo server. "
                + "Return the tool's response verbatim.",
            bodyMd.length() > 80 ? bodyMd.substring(0, 80) + "..." : bodyMd,
            title
        );
        return chatClient.prompt()
            .system("""
                You are a notification sub-agent. You MUST use the send_echo
                tool to deliver the digest. Do not skip the tool call — the
                pipeline is only complete when the tool returns OK.
                """)
            .user(userPrompt)
            .call()
            .content();
    }
}
