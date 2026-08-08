package com.example.aicuration.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Explicit ChatClient bean. Spring AI 2.0 does not auto-wire a default
 * ChatClient — we expose one built on the auto-configured ChatModel
 * (the OpenAI-compatible model, in this demo pointed at the Doubao Ark
 * Coding endpoint).
 *
 * <p>Both the main ReAct agent and the sub-agents inject this single
 * ChatClient and apply per-instance tools/advisors via {@code mutate()}.
 */
@Configuration
public class ChatClientConfig {

    @Bean
    public ChatClient defaultChatClient(ChatModel chatModel) {
        return ChatClient.builder(chatModel).build();
    }
}
