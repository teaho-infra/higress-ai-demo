# Spring AI Demo

ReAct Agent + Skills + MCP demo,验证 Higress AI 资产管理。

## 启动

```bash
# 前置
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH=$JAVA_HOME/bin:$HOME/soft/maven/apache-maven-3.8.2/bin:$PATH
export OPENAI_API_KEY=your-ark-key
export OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
export OPENAI_MODEL=deepseek-v4-flash-ga-260731

# 起服务
mvn spring-boot:run
```

## 验证

```bash
curl http://localhost:8088/ping
curl http://localhost:8088/actuator/health
```

## 模块

- `domain/` — DDD 领域模型(DailyDigestTask, Article)
- `application/` — Use cases
- `infrastructure/` — MCP / LLM 网关 client
- `skills/` — 本地 @Tool Skills
- `agent/` — 主 ReAct Agent + Sub-agents
- `api/` — REST controllers

## Tech stack

- Spring Boot 4.0.0
- Spring AI 2.0.0
- Java 21
- LLM: 豆包 Ark Coding (OpenAI 兼容)
