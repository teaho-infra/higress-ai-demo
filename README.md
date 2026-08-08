# Higress AI Demo (含 HiMarket)

本地 PoC 仓库,演示 **Higress AI 网关 + HiMarket AI 业务平台 + Spring AI 2.0 ReAct Agent + MCP** 的完整链路。

> 设计文档: [`plan/design.md`](plan/design.md)(指向 `~/.hermes/plans/2026-08-08_150851-higress-ai-demo-design.md`)

---

## 1. 组件

| 层级 | 组件 | 路径 | 用途 |
|---|---|---|---|
| **网关** | Higress all-in-one (via HiMarket) | `docker` container | LLM 网关 / MCP 路由 / 插件 |
| **业务平台** | HiMarket 8 容器 | `~/IdeaProjects/agentspace/himarket/` | Provider / MCP / Agent / Skill / Worker 上架 |
| **服务发现** | Nacos 3.2.1 (via HiMarket) | `docker` container | 配置中心 + 服务发现 |
| **Demo 后端** | Spring Boot 4.0 + Spring AI 2.0 | `spring-ai-demo/` | ReAct Agent + @Tool Skills + MCP client |
| **Skills** | `SummarizeArticles` + `BuildDigestMarkdown` | `spring-ai-demo/src/main/java/.../skills/` | 本地 @Tool,纯字符串处理 |
| **MCP servers** | rss-fetcher + notifier | `mcp-servers/` | stdio 模式,Spring AI 直接 fork |
| **Echo server** | Python stdlib HTTP | `mcp-servers/scripts/echo_server.py` | 验证通知链路(端口 9999) |

---

## 2. 一键启动

### 2.1 HiMarket(全部基础设施,8 容器)

```bash
cd ~/IdeaProjects/agentspace/himarket/deploy/docker
NON_INTERACTIVE=1 bash install.sh --non-interactive
# 首次需要 ~5 分钟拉镜像 + 启动
```

启动后端口(本机,避开系统占用):

| 端口 | 服务 | 凭证 |
|---|---|---|
| **15174** | HiMarket Admin Console | `admin / Zx6PDO4gjQkBInJG` |
| **15173** | HiMarket Developer Portal | `user / 7dMoWuxk9lhVeZv1` |
| **18081** | HiMarket Server API | Bearer token |
| **18001** | Higress Console | `admin / K3o2xvubqbsVBQWv` |
| **18080** | Higress Gateway HTTP | — |
| **19080** | Nacos Console | `nacos / sCCKusJpr45S4YIh` |
| **33306** | MySQL (HiMarket + Nacos 共享) | `root / Rv5XIC4abLOMMGZT` |
| **18443** | Higress Gateway HTTPS | — |

凭证文件: `~/himarket-install-docker.env`(deploy 脚本自动写)。

### 2.2 Spring AI Demo

```bash
cd ~/IdeaProjects/agentspace/higress-ai-demo/spring-ai-demo
export OPENAI_API_KEY=***        # 你的豆包 Ark key(不写文件)
export OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
export OPENAI_MODEL=deepseek-v4-flash-ga-260731
bash -lc 'mvn -q -B spring-boot:run'
# 端口 8088
```

### 2.3 Echo server

```bash
cd ~/IdeaProjects/agentspace/higress-ai-demo/mcp-servers/scripts
python3 echo_server.py  # 端口 9999
```

### 2.4 触发 digest pipeline

```bash
# 1) 验证 MCP 链路
curl http://localhost:8088/ping
curl http://localhost:8088/admin/tools  # 应该 count=4: list_feeds/search_rss/send_webhook/send_echo

# 2) 触发 ReAct pipeline(需要真 OPENAI_API_KEY)
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"AI","maxItems":3}' \
  http://localhost:8088/digest

# 3) 验证 echo server 收到 markdown
curl http://localhost:9999/recent
```

---

## 3. 架构

```
                    ┌─────────────────┐
                    │   User/Codex    │
                    └────────┬────────┘
                             │
            ┌────────────────┼─────────────────┐
            │                │                 │
            ▼                ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ HiMarket UI  │  │ HiMarket API │  │  Codex CLI   │
    │  15173/15174 │  │    18081     │  │  (debug)     │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           │                 │                 │
           └────────────────┬┴─────────────────┘
                            │
                ┌───────────▼────────────┐
                │ Higress Gateway 18080  │  ← AI 路由/插件/MCP
                │ + Console 18001        │
                └───────────┬────────────┘
                            │
              ┌─────────────┴────────────┐
              │                          │
              ▼                          ▼
    ┌──────────────────┐        ┌──────────────────┐
    │ Nacos 19080      │        │  Spring AI Demo  │
    │ config + service │        │  8088            │
    └────────┬─────────┘        └────────┬─────────┘
             │                           │
             └─────────┬─────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ 豆包 Ark Coding │
              │  /v3 OpenAI API │
              └─────────────────┘

    Spring AI Demo 内部:
        ┌────────────────────────────────────────┐
        │ MainReActAgent (ChatClient)            │
        │   ├─ SubAgentRssSearcher              │
        │   │    └─ MCP: rss-fetcher (stdio)    │
        │   ├─ SubAgentNotifier                 │
        │   │    └─ MCP: notifier (stdio)       │
        │   ├─ @Tool SummarizeArticles          │
        │   └─ @Tool BuildDigestMarkdown        │
        │   (ToolCallingAdvisor 自动 loop)      │
        └────────────────────────────────────────┘
```

---

## 4. 关键决策(why this, not that)

| 决策 | 选了什么 | 原因 |
|---|---|---|
| LLM 端点 | 豆包 Ark Coding (`api/coding/v3`) | 你已有 key,OpenAI 兼容,延迟低 |
| 镜像源 | 阿里云杭州 ACR (`*-registry.cn-hangzhou.cr.aliyuncs.com`) | 国内网速稳定,Docker Hub 太慢 |
| MCP 接入 | Spring AI MCP client **stdio**(非 SSE/HTTP) | 简洁,无鉴权,适合本地 |
| HiMarket 部署 | 一键 `install.sh` (8 容器) | 给 Codex 调试用,自带 Higress + Nacos |
| JDK 21 路径 | `/usr/lib/jvm/java-21-openjdk-amd64/` (系统) | 避免 SDKMAN,环境简单 |
| Maven 3.8.2 | `~/soft/maven/apache-maven-3.8.2/` | 你已有;3.9+ 仍兼容,3.8.2 够用 |
| Task 6 | 跳过 Higress Console 注册 MCP | MCP server 走 stdio,不需要 Higress 转一道 |
| Task 7b | 跳过 Nacos config 集成 | Demo 跑用 env var 够;留到生产再上 |
| Task 10 真实 key | 未跑(等用户提供) | 架构验证通过(fake key 拿到 401 = 链路通) |
| Task 10b 端口偏移 | 避开系统 3306/8080/8001 | 系统 MySQL + 03-agent-build-docker 占用 |

---

## 5. 测试

### 5.1 Python MCP servers

```bash
cd mcp-servers/rss-fetcher && uv run pytest -v    # 3 tests
cd mcp-servers/notifier     && uv run pytest -v    # 5 tests
```

### 5.2 Spring AI Skills

```bash
cd spring-ai-demo
bash -lc 'mvn -q -B test'    # SkillsTest 5 tests
```

### 5.3 集成验证

```bash
# Spring Boot 启动后
curl http://localhost:8088/admin/tools
# {"count":4,"tools":[{name:list_feeds},...{name:send_echo}]}
```

---

## 6. 运维命令

```bash
# 启动全部
cd ~/IdeaProjects/agentspace/himarket/deploy/docker
docker compose up -d
docker ps | grep -E "himarket|nacos|higress"

# 查 HiMarket 日志
docker logs -f docker-himarket-server-1

# 重启某个服务
docker compose restart himarket-server

# 停全部
docker compose down
# 数据保留在 ~/himarket-data/

# 完全卸载(连数据)
bash install.sh --uninstall
# 然后 rm -rf ~/himarket-data/

# Spring AI Demo 启停
cd ~/IdeaProjects/agentspace/higress-ai-demo/spring-ai-demo
bash -lc 'mvn -q -B spring-boot:run'   # 启
pkill -f spring-boot:run                # 停

# Echo server
cd mcp-servers/scripts && python3 echo_server.py
pkill -f echo_server.py
```

---

## 7. 已知问题 / 后续

1. **真 Ark key 跑端到端 E2E** — 当前 401 是 fake key 预期;真 key 走通后 `curl /digest` 应收到 markdown 进 echo
2. **HiMarket ↔ Higress MCP server 双向同步** — 当前没做(留 Codex 调试时按需)
3. **Nacos config 集成** — Demo 用 env var 够,生产上 `spring-cloud-starter-alibaba-nacos-config`
4. **Codex CLI 调试** — 计划用 `qodercli` 或 `claude-agent-acp`(HiMarket sandbox 已支持)
5. **API key 管理** — 当前 `~/.hermes/config.yaml` 里有,生产迁到 vault / 容器 secret
6. **HiMarket MCP server marketplace** — 可把我们 rss-fetcher/notifier 注册进去,做产品化

---

## 8. 目录结构

```
higress-ai-demo/
├── .gitignore
├── README.md                      ← 本文件
├── plan/
│   └── design.md                  → ~/.hermes/plans/...-design.md (软链)
├── infra/
│   ├── docker-compose.yml         (Nacos 2.5.3 + Higress 2.2.3, 手装版,已停)
│   ├── .env.example               (环境变量模板)
│   ├── README.md                  (服务速查)
│   ├── NOTES.md                   (部署备注)
│   ├── ark-validation.md          (豆包 Ark 端点 key 验证记录)
│   └── data/                      (docker volume)
├── mcp-servers/
│   ├── rss-fetcher/               (Python stdio MCP)
│   │   ├── pyproject.toml
│   │   ├── src/rss_fetcher/server.py
│   │   └── tests/test_server.py
│   ├── notifier/                  (Python stdio MCP)
│   │   ├── pyproject.toml
│   │   ├── src/notifier/server.py
│   │   └── tests/test_server.py
│   └── scripts/echo_server.py     (9999 端口 echo)
└── spring-ai-demo/                (Java 21 + Spring Boot 4 + Spring AI 2)
    ├── pom.xml
    ├── README.md
    └── src/
        ├── main/java/com/example/aicuration/
        │   ├── AiCurationApplication.java
        │   ├── api/              (PingController / AdminController / DigestController)
        │   ├── agent/            (MainReActAgent / 2 SubAgents / AgentWiring)
        │   ├── config/           (ChatClientConfig)
        │   ├── domain/           (Article)
        │   └── skills/           (SummarizeArticles / BuildDigestMarkdown)
        └── test/java/.../skills/SkillsTest.java
```

---

## 9. 相关仓库

- **HiMarket**(独立项目): `~/IdeaProjects/agentspace/himarket/`
  - 8 容器 compose: `deploy/docker/`
  - 后端 monorepo: `himarket-server/`
  - Admin: `himarket-web/himarket-admin/`
  - Frontend: `himarket-web/himarket-frontend/`
  - 沙箱: `sandbox-shared`(`qodercli`/`qwen`/`claude-agent-acp`/`opencode`)
  - AGENTS.md: HiMarket 自己的 Agent 工作约束(自动注入上下文)
