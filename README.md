# higress-ai-demo

本地搭建 **Higress + Nacos**(以及可选的 **HiMarket**),并实现一个 **Spring AI 2.0** ReAct Agent Demo,验证 **Skills(@Tool 本地)** 和 **MCP(远程协议)** 两条工具调用链路。业务功能:**每日 RSS AI 日报检索 + 推送**。

完整设计文档:[`plan/design.md`](plan/design.md)

## 目录结构

```
higress-ai-demo/
├── infra/           # docker-compose:Nacos + Higress(+ 将来 HiMarket)
├── mcp-servers/     # MCP 协议实现(Python)
│   ├── rss-fetcher/ # 抓 RSS
│   └── notifier/    # 推送 webhook
├── spring-ai-demo/  # Spring Boot 4 + Spring AI 2 Demo
└── plan/            # 设计文档 + 调研报告
```

## 快速开始

> 前置:JDK 21 / Maven 3.9 / Docker 29+

```bash
# 1. 启动 Nacos + Higress
cd infra
cp .env.example .env   # 填上真实 OPENAI_API_KEY
docker compose up -d

# 2. 启动 echo server(Task 5)
python3 mcp-servers/scripts/echo_server.py &

# 3. 启动 Spring AI Demo
cd spring-ai-demo
mvn spring-boot:run
```

## 端口速查

| 服务 | 端口 | 凭证 |
|---|---|---|
| Nacos Console | 8848 | nacos/nacos |
| Higress Console | 8001 | admin/admin |
| Higress Gateway | **8082** (8080 被占) | — |
| Higress Gateway(HTTPS) | 8443 | — |
| Spring AI Demo | 8088 | — |
| Echo server | 9999 | — |
| HiMarket Admin | 5174 | admin/admin |
| HiMarket Portal | 5173 | — |
| HiMarket Server | 8081 | — |
| HiMarket 内置 Higress | 8001 / 8082 | admin/admin |

## License

Private/Internal.
