package com.example.aicuration.api;

import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * Read-only diagnostic endpoint that returns the tools Spring AI knows about
 * (both locally declared @Tool methods and any tools registered by MCP servers).
 *
 * Useful to verify the MCP stdio clients are actually starting the Python servers.
 */
@RestController
@RequestMapping("/admin")
public class AdminController {

    private final ToolCallbackProvider toolCallbackProvider;

    public AdminController(ToolCallbackProvider toolCallbackProvider) {
        this.toolCallbackProvider = toolCallbackProvider;
    }

    @GetMapping("/tools")
    public Map<String, Object> listTools() {
        ToolCallback[] callbacks = toolCallbackProvider.getToolCallbacks();
        List<Map<String, String>> tools = new java.util.ArrayList<>();
        for (ToolCallback cb : callbacks) {
            tools.add(Map.of(
                "name", cb.getToolDefinition().name(),
                "description", cb.getToolDefinition().description()
            ));
        }
        return Map.of("count", tools.size(), "tools", tools);
    }
}
