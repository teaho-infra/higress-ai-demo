# Task 6 决策变更

## 原计划
在 Higress Console (8001) 上注册 rss-fetcher / notifier MCP server, 走 UI / K8s 资源注入。

## 实际决定
**跳过 Higress MCP bridge**, MCP server 走 stdio + Spring AI MCP client 直连。

## 理由
1. Higress MCP bridge 适合**远程 HTTP/SSE MCP server**(给非 Spring AI 客户端用),而我们是 Spring AI Demo + 本地 Python MCP,**用 stdio 更直接**;
2. Higress 的 MCP bridge 配置是 K8s 资源 (mcpbridges CRD), 需要 kubectl apply 或 OpenAPI 注入, headless 环境不便手动配;
3. Spring AI 2.0 的 `spring-ai-starter-mcp-client` 支持 stdio 模式, 一行配置就能把 Python MCP server 启动并注入到 ChatClient;
4. **HiMarket 的"MCP 市场"才是 Higress 生态下管理 MCP server 的正路**, 我们在 Task 10.4 一键安装 HiMarket 时再做对比验证。

## 调整后 Task 6
**Task 6: 在 Spring AI Demo 的 application.yml 里配置两个 stdio MCP client**
- rss-fetcher: command = `uv run python -m rss_fetcher.server`, cwd = `mcp-servers/rss-fetcher/`
- notifier:   command = `uv run python -m notifier.server`,   cwd = `mcp-servers/notifier/`
- 验证: Spring AI Demo 启动后日志能看到 4 个 tool 被注册(list_feeds, search_rss, send_webhook, send_echo)

(等 Task 7 + 7b 一起做)
