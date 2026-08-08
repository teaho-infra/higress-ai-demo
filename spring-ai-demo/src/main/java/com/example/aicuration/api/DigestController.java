package com.example.aicuration.api;

import com.example.aicuration.agent.MainReActAgent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Triggers the daily-digest ReAct pipeline.
 *
 * <p>Body (all fields optional):
 * <pre>
 * {
 *   "sinceIso": "2026-08-07T00:00:00Z",  // default = 24h ago
 *   "query":    "AI",                    // optional filter
 *   "maxItems": 10                       // default 20
 * }
 * </pre>
 */
@RestController
@RequestMapping("/digest")
public class DigestController {

    private final MainReActAgent agent;

    public DigestController(MainReActAgent agent) {
        this.agent = agent;
    }

    @PostMapping
    public Map<String, Object> runDigest(@RequestBody(required = false) DigestRequest body) {
        if (body == null) body = new DigestRequest(null, null, null);
        String since = body.sinceIso() == null ? "" : body.sinceIso();
        String query = body.query() == null ? "" : body.query();
        int max = body.maxItems() == null ? 20 : body.maxItems();

        String result = agent.run(since, query, max);

        return Map.of(
            "ok", true,
            "sinceIso", since.isBlank() ? "(default 24h ago)" : since,
            "query", query.isBlank() ? "(none)" : query,
            "maxItems", max,
            "agentResponse", result
        );
    }

    public record DigestRequest(String sinceIso, String query, Integer maxItems) {}
}
