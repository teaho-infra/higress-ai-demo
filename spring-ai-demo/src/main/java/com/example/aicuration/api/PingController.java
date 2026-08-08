package com.example.aicuration.api;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.Map;

/**
 * Health/liveness probe. Also useful as the very first thing to hit
 * after the Spring Boot app starts.
 */
@RestController
public class PingController {

    @GetMapping("/ping")
    public Map<String, Object> ping() {
        return Map.of(
            "status", "UP",
            "service", "spring-ai-demo",
            "ts", Instant.now().toString()
        );
    }
}
