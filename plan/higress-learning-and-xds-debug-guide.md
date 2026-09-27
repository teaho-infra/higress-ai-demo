# Higress 系统入门 + Controller/Gateway 交互故障排查指南

> **读者**：刚入门的 AI/API 网关开发，会用 `curl`、看得懂 YAML，K8s/Envoy 零基础也没关系。
> **目标**：① 建立 Higress 整体架构心智模型；② 按路线系统学习；③ **掌握一套可复用的方法，
> 独立定位「higress-controller 与 higress-gateway 交互失败/报错」类问题**。
> **配套阅读**：`bookspace/book_notes/notes_docs/blogs/ainotes/higress-gateway/higress-gateway.md`（学习笔记，本文在其基础上强化了架构与排障部分）。
>
> 本文命令分两种形态给出：**standalone**（本机 all-in-one 容器 `higress`）与 **K8s**（minikube + Helm）。
> 标注「本机实测」的内容均来自 2026-09 本仓库真实环境。

---

## 目录

- [Part 0 · 一分钟速查](#part-0--一分钟速查)
- [Part 1 · 架构说明](#part-1--架构说明)
- [Part 2 · Controller ↔ Gateway 交互失败排查（核心）](#part-2--controller--gateway-交互失败排查核心)
- [Part 3 · Step-by-step 六周学习路线](#part-3--step-by-step-六周学习路线)
- [Part 4 · 网上学习资料](#part-4--网上学习资料)
- [Part 5 · 入门自测清单](#part-5--入门自测清单)
- [附录 · 术语表](#附录--术语表)

---

## Part 0 · 一分钟速查

**三句话记住 Higress：**

1. **Envoy 干活**：每个请求都由数据面的 Envoy（C++ 代理）转发。
2. **xDS 是神经**：控制面通过 xDS（LDS/RDS/CDS/EDS）把「监听、路由、集群、端点」推给 Envoy，热生效、不重启。
3. **插件是扩展点**：AI 网关等差异化能力大多以 Wasm 插件挂在 Envoy 请求链路上。

**「controller 和 gateway 交互失败」先看什么（30 秒分诊）：**

```bash
# standalone（本机 all-in-one 容器）
docker exec higress ps aux | grep -E 'pilot-discovery|envoy'   # 两个进程都在吗？
docker exec higress ss -ltnp | grep -E '15010|15012|15051|80'  # xDS 和网关端口在听吗？
tail -80 /var/log/higress/gateway.log   # 经 docker exec higress 执行；看最后一条 error
curl -s http://127.0.0.1:18080/ -o /dev/null -w '%{http_code}\n'  # 000=端口无人监听

# K8s（minikube）
kubectl -n higress-system get pods                              # controller/gateway 都 Ready 吗？
kubectl -n higress-system logs deploy/higress-controller --tail=100
kubectl -n higress-system logs <gateway-pod> -c istio-proxy --tail=100
kubectl -n higress-system get events --sort-by=.lastTimestamp | tail -20
```

> **本机实测（2026-09-27）**：当前容器 `higress` 处于 `unhealthy`——`pilot-discovery`（controller 侧）
> 正常、Console 18001 返回 200，但 **Envoy 进程已不存在**，18080 返回 `000`。根因是
> `too many open files`（详见 [2.5 实战复盘](#25-实战复盘本机-2026-09-25-故障too-many-open-files)）。

---

## Part 1 · 架构说明

### 1.1 一张全景图

```
客户端
  │  HTTP / HTTPS
  ▼
┌───────────────────────────────────────────────────────┐
│  控制面 Control Plane（不转发业务流量）                  │
│                                                       │
│  配置输入：K8s Ingress / Gateway API / Istio CRD /      │
│           Nacos / Console UI                          │
│                          │                            │
│              ┌───────────▼────────────┐               │
│              │ higress-controller      │  监听资源，     │
│              │ （higress core，Go）    │  翻译生成统一   │
│              │  :8888/debug/configz    │  配置模型       │
│              └───────────┬────────────┘               │
│                          │ MCP over xDS               │
│              ┌───────────▼────────────┐               │
│              │ pilot-discovery (Istio) │  计算每个       │
│              │  xDS gRPC :15010/:15012 │  Envoy 的最终  │
│              │  debug :15014           │  配置并推送     │
│              └───────────┬────────────┘               │
└──────────────────────────┼────────────────────────────┘
                           │ xDS（ADS 聚合 gRPC 流，LDS/RDS/CDS/EDS）
                           ▼
┌───────────────────────────────────────────────────────┐
│  数据面 Data Plane = higress-gateway                   │
│                                                       │
│  pilot-agent（守护/引导）                               │
│      └─ Envoy：listener → route → cluster → endpoint   │
│      认证 / 限流 / 改写 / AI 插件在这里逐请求执行         │
│      admin :15000（config_dump / clusters / stats）     │
└───────────────┬───────────────────────┬───────────────┘
                ▼                       ▼
          上游业务服务              LLM Provider / MCP Server
```

**一次配置变更的旅程**：你在 Console/CRD 提交一条路由 → controller watch 到事件、
翻译成内部配置 → 经 MCP over xDS 同步给 pilot-discovery → pilot 计算增量、
通过 xDS gRPC 流推给所有已连接的 Envoy → Envoy 在 **1～15 秒内**热加载生效。

### 1.2 Higress 的三个身份与两种部署形态

- **三个身份合一**：Ingress 网关（替代 Nginx Ingress，南北向）、服务网格网关
  （东西向治理：限流/熔断/灰度）、**AI 网关**（多模型路由、Key 管理、Token 限流、语义缓存——当前主线）。
- **内核**：Envoy + Istio（Istio 的 pilot-discovery 保留，Istio Pilot 上游那部分重写为 Higress Controller），
  兼容 K8s Ingress / Gateway API / Istio CRD，并支持 Nacos 作为非 K8s 配置源。

| | **standalone all-in-one**（本机现有） | **K8s Helm**（minikube 迁移目标） |
|---|---|---|
| 部署物 | 单容器，supervisord 管 6+ 进程 | controller Deployment + gateway Pod + console + 内置 Nacos |
| 配置入口 | Console / Nacos / 容器内 `/data/*.yaml` | `kubectl apply`（Ingress/CRD）/ Console |
| xDS 链路 | 全部走容器内 loopback | gateway Pod → controller Service（默认同 Pod sidecar/同节点） |
| 适合 | 学习、PoC、无 K8s 环境 | 生产、标准实验环境 |
| 文档 | [docker-compose 独立部署](https://higress.cn/docs/latest/ops/deploy-by-docker-compose/) | [Helm 云原生部署](https://higress.cn/docs/latest/ops/deploy-by-helm/) |

### 1.3 all-in-one 容器进程地图（本机实测，2026-09）

容器 `higress`（镜像 `higress/all-in-one`）内由 supervisord 拉起：

| 进程 | 角色 | 关键端口 |
|---|---|---|
| `nginx` | Console/前端的入口反代 | 容器 8002（宿主 18001→8001 走 java） |
| `apiserver` | standalone 内置的「类 K8s APIServer」，承载本地资源对象 | 127.0.0.1:18443 |
| `higress serve`（**controller core**） | watch 资源、翻译配置、对 pilot 提供配置 | 8888 / 8889 / 15051 |
| `pilot-discovery discovery`（**Istio Pilot**） | xDS server，向 Envoy 下发 LDS/RDS/CDS/EDS | **15010/15012**（gRPC）、**15014**（debug）、15080（HTTP） |
| `pilot-agent + envoy`（**gateway**） | 数据面；pilot-agent 生成 bootstrap、守护 Envoy | 80/443（业务）、15000（admin）、15020（status） |
| `java -jar higress-console.jar` | Console 后端（路由/插件 UI） | 8001 |
| `plugin-server` | 进程外插件服务 | — |

启动顺序由 supervisord `priority` 与脚本内等待控制：`start-gateway.sh` 里有 **`waitForPilot`**
——gateway 必须等 pilot 就绪才启动。这解释了一类启动时序故障（见 2.6）。

### 1.4 数据面四件套 ↔ xDS 对应关系

| Envoy 概念 | 含义 | Higress 配置来源 | xDS 接口 |
|---|---|---|---|
| Listener | 监听端口（80/443）及过滤链 | 网关 Deployment/全局配置 | **LDS** |
| Route | 域名+路径 → 上游的规则、虚拟主机 | Ingress / IngressRoute | **RDS** |
| Cluster | 一个上游服务的连接池、LB 策略、熔断 | McpBridge / Service / 静态 DNS | **CDS** |
| Endpoint | Cluster 后的具体 IP:Port 列表 | Nacos / K8s Endpoints / 静态 | **EDS** |

请求路径：`listener 收到 → HCM 过滤链 → 命中 route → 找到 cluster → 挑一个 endpoint → 发出`。

### 1.5 xDS 协议深入（排障必须理解的细节）

- xDS 是一套 **gRPC 流式订阅协议**。每个 xDS 接口都是「Envoy 发起请求（订阅资源）↔ server 流式返回」。
- **ADS（Aggregated Discovery Service）**：把 LDS/RDS/CDS/EDS 复用到**一条 gRPC 双向流**上
  （`/envoy.service.discovery.v3.AggregatedDiscoveryService/DeltaAggregatedResources` 或 SotW 版本），
  保证多种资源的更新顺序。Higress 默认走 ADS，端点 15010（plain）/15012（mTLS）。
- **SotW vs Delta**：SotW（State of the World）每次推全量；Delta xDS 只推增减。版本演进中两种都可能出现。
- **ACK/版本号机制**：每个 Response 带 `version_info`，Envoy 处理完后在下次 Request 里回带该版本号 +
  `response_nonce`；server 靠 nonce 判断上次推送是否被接受。**Envoy 拒绝配置时会回 `error_detail`**——
  这是定位「配置下发了但不生效」的关键信号（在 pilot 日志里搜 `NACK`/`rejecting`）。
- standalone 中 gateway 的 bootstrap（本机实测，`gateway.log` 里打印的 mesh config）：
  - `discoveryAddress: 127.0.0.1:15012`，`controlPlaneAuthPolicy: MUTUAL_TLS`；
  - `configSources: xds://127.0.0.1:15051` 与 `k8s://`；`PROXY_XDS_VIA_AGENT=true`（经 pilot-agent 中转）；
  - `serviceCluster: higress-gateway`，`rootNamespace: higress-system`。
- Envoy 启动时先加载**静态 bootstrap**（listener/admin/ADS cluster），连上 ADS 后，后续一切配置皆动态。

### 1.6 证书与信任

- standalone 首次启动时 `start-pilot.sh initCerts` 用 OpenSSL 自签生成 `/etc/certs/`
  （`root-cert.pem`、`cert-chain.pem`、`ca-key.pem` 等，有效期 36500 天），pilot 与 gateway 共用，
  xDS 走 **mTLS**。
- 排障含义：证书文件缺失/损坏/被换 → xDS 握手失败，Envoy 拿不到任何配置（见 2.6 模式②）。
  日志特征：`certificate verify failed`、`SSLV3_ALERT`、`auth handshake error`。

### 1.7 Wasm 插件在链路中的位置

```
请求:  requestHeaders → requestBody
                │  上游业务 / LLM
响应: responseHeaders → responseBody
```

- Higress Controller 把 Higress `WasmPlugin` CR 转成 Istio `WasmPlugin`（转换代码
  `pkg/ingress/config/ingress_config.go` 的 `convertIstioWasmPlugin`），经 MCP over xDS → pilot → Envoy。
- 支持三级匹配：`_match_domain_` / `_match_route_` / `_match_service_`。
- AI 场景注意：插件同时介入请求（注入 Provider Key、选模型）与响应（Token 统计、SSE 处理），
  **绝不能缓冲整个流式响应**，否则打字机效果卡死。
- 参考：[Wasm 生效原理](https://higress.io/docs/latest/plugins/wasm-dev/wasm19/)、[30 行代码写一个 Wasm Go 插件](https://higress.cn/blog/30-line-wasm/)。

---

## Part 2 · Controller ↔ Gateway 交互失败排查（核心）

### 2.1 五层故障模型

任何「controller/gateway 交互失败」都可以归入下面五层之一。**从上往下逐层排除，不要跳层猜**。

| 层 | 典型问题 | 一眼指标 |
|---|---|---|
| **L1 进程层** | Envoy/pilot/controller 进程挂了、OOM、启动即崩、supervisord FATAL | `ps` 缺进程、Pod 非 Running、容器 unhealthy |
| **L2 网络/证书层** | xDS 端口不通、DNS/Service 错、mTLS 证书坏、NetworkPolicy/防火墙 | `ss/telnet` 不通、握手失败日志 |
| **L3 xDS 会话层** | ADS 连接建立但断开/重连、Envoy NACK、版本不匹配 | pilot 日志的 connect/disconnect/**NACK**、`/debug/connections` |
| **L4 配置翻译层** | 资源没被 watch 到、ingressClassName 不符、McpBridge/Nacos 源错、转换被忽略 | `configz` 里没有该资源、controller 日志 warn |
| **L5 上游/流量层** | xDS 全正常，但路由 404/503/超时：无 endpoint、Strip 前缀、TLS 到上游 | Envoy `config_dump` 正常但请求失败、access log `response_flags` |

> 经验：新人最容易把 L5（上游问题）误判为 L3（控制面问题）。**只要 config_dump 里能看到你的路由，
> 控制面就是好的，问题在 L5。**

### 2.2 症状 → 排查层级速查表

| 症状 | 最可能层 | 先做什么 |
|---|---|---|
| 容器 `unhealthy`，curl 网关 `000`（连接拒绝） | L1 | 查进程与 `gateway.log` 最后一条 error |
| Console 能开，网关没响应 | L1 | Console 是 java，挂了也不影响；单查 Envoy 进程 |
| Pod `CrashLoopBackOff` | L1 | `kubectl logs --previous` 看上次崩溃原因 |
| 日志反复 `StreamAggrResources ... close`、重连 | L2/L3 | 查 15010/15012 连通与证书 |
| `xds: connection termination` / `certificate verify failed` | L2 | 查 `/etc/certs`、时间是否被重置 |
| pilot 日志出现 `NACK` / `rejecting configuration` | L3/L4 | 看 NACK 的 error_detail，多为 Envoy 版本不支持该配置 |
| 路由在 Console 列表里，但请求 404 | L4/L5 | configz 三段比对；查域名/Host 头匹配 |
| 请求返回 503 `no healthy upstream` | L5 | 查 EDS endpoint、健康检查、McpBridge/Nacos 实例 |
| 配置改了，十几秒还不变 | 非故障 | xDS 秒级延迟（10–15s），轮询等待再断言 |
| K8s apply 了 Ingress，完全无反应 | L4 | 是否带 `ingressClassName: higress`；namespace 是否被 watch |
| Envoy 启动报 `too many open files` | L1 | 见 2.5 实战复盘 |

### 2.3 工具箱：三段 Debug 端点（配置链路逐段截查）

配置链路是 **controller → pilot → envoy** 三段，每段都有一个「快照接口」，
**在哪段断了，问题就在哪段的上游侧**：

```bash
# K8s：先 kubectl exec -n higress-system 进 controller Pod；standalone：docker exec -it higress sh

# ① controller 生成的全量配置（没有你的路由 → 问题在 L4：资源没被 controller 接收/翻译）
curl -s 'http://127.0.0.1:8888/debug/configz?pretty' | less

# ② pilot 从 controller 收到的配置（①有②无 → controller→pilot 的 MCP over xDS 有问题）
curl -s 'http://127.0.0.1:15014/debug/configz?pretty' | less

# ② 查看当前与各 Envoy 的 xDS 连接（看不到 gateway 连接 → L2/L3：Envoy 没连上或被断开）
curl -s 'http://127.0.0.1:15014/debug/connections'
# 取 connectionId(proxyID)，查 pilot 实际推给某个 Envoy 的配置（②有、③无 → 推送/接收环节）
curl -s 'http://127.0.0.1:15014/debug/config_dump?proxyID=<connectionId>&pretty' | less

# ③ Envoy 侧最终生效配置（在 gateway Pod / standalone 容器内）
curl -s 'http://127.0.0.1:15000/config_dump' | less
curl -s 'http://127.0.0.1:15000/clusters'          # cluster 与每 endpoint 的健康/指标
curl -s 'http://127.0.0.1:15000/stats' | grep -E 'update_(success|rejected)|xds'
curl -s 'http://127.0.0.1:15020/healthz/ready'     # pilot-agent 就绪探针
```

其他常用：

```bash
# 日志文件（standalone，supervisord 各程序独立落盘）
/var/log/higress/{controller,pilot,gateway,apiserver,console,supervisord}.log

# K8s 事件与日志
kubectl -n higress-system get events --sort-by=.lastTimestamp | tail -30
kubectl -n higress-system logs deploy/higress-controller [-c <container>] --tail=200
kubectl -n higress-system logs <gateway-pod> -c istio-proxy --tail=200
kubectl -n higress-system describe pod <pod>      # 看探针失败、OOMKilled、拉镜像失败

# xDS 计数（Envoy stats）：rejected > 0 即 Envoy 在 NACK 配置
curl -s http://127.0.0.1:15000/stats | grep -E 'cluster.xds|update_rejected|update_attempt'
```

官方文档：[查看运行时配置](https://higress.io/en/docs/latest/ops/how-tos/view-configs/)。

### 2.4 标准排查 SOP（按顺序做，每步记录证据）

1. **现象定性**：`curl -sv` 复现，记录状态码（`000`/404/503/401/5xx）与 Host 头。
2. **L1 查进程**：standalone `ps aux`+`ss -ltnp`；K8s `get pods`+`describe pod`。
   - Pod 重启过 → 必看 `logs --previous`。
3. **若进程缺失/崩溃**：读对应程序日志的**最后一条 error**，定位启动失败原因（资源、证书、FD、配置）。
   先让进程起来，再谈交互。
4. **L2 验证连通**：从 gateway 侧 telnet/curl xDS 端口（15010/15012/15051）；查证书与时间。
5. **L3 看会话**：pilot `/debug/connections` 里有没有 gateway；pilot 日志搜
   `connect|disconnect|NACK|reject|ADS`。
6. **三段 configz 比对**：8888 → 15014 → Envoy 15000，找出配置在哪一段消失。
7. **L4 查资源合法性**：`ingressClassName: higress`、namespace、域名、McpBridge/Nacos 服务源、CRD 是否存在。
8. **L5 查上游**：`/clusters` 看 endpoint 健康；进 gateway Pod/容器手动 `curl` 上游地址；
   查路径 Strip、TLS、超时。
9. **看 Envoy NACK 细节**：stats 里 `update_rejected`，pilot 日志里的 error_detail——
   常见为配置用了当前 Envoy 版本不支持的字段。
10. **等待收敛**：改动后 sleep 10～15 再验证，避免把延迟当故障。
11. **版本对齐核对**：controller / pilot / Envoy 是否同源版本（混用镜像最容易出 NACK）。
12. **记录与固化**：把根因、关键日志、修复写入 plan/ 或提交信息。

### 2.5 实战复盘：本机 2026-09-25 故障（too many open files）

这是一个标准的 L1 进程层故障，却表现为「controller 活着、gateway 死了」的交互中断，完整证据链如下。

**现象**

```bash
docker ps                      # higress  Up 2 days (unhealthy)
curl 127.0.0.1:18001 → 200     # Console（java + nginx）正常
curl 127.0.0.1:18080 → 000     # 网关端口无人监听；健康检查 exit 7（curl couldn't connect）
docker exec higress ps aux | grep envoy    # 无任何 envoy/pilot-agent 进程
docker exec higress ss -ltnp   # pilot-discovery 的 15010/15012/15014 都在，唯独没有 80
```

**追日志**：`gateway.log` 最后一条——

```text
2026-09-25T01:35:17  info  Opening status port 15020
Error: failed to start default Istio SDS server: failed to start workload secret manager too many open files
2026-09-25T01:35:17 error  failed to start default Istio SDS server: ... too many open files
```

**supervisord 侧**（`/var/log/higress/supervisord.log`）——Envoy 连续启动失败 5 次后被放弃：

```text
01:35:09 INFO exited: gateway (exit status 255; not expected)
01:35:10 INFO spawned ... 01:35:10 INFO exited (exit status 255)
01:35:11 INFO spawned ... 01:35:11 INFO exited (exit status 255)
01:35:13 INFO spawned ... 01:35:13 INFO exited (exit status 255)
01:35:16 INFO spawned ... 01:35:17 INFO exited (exit status 255)
01:35:18 INFO gave up: gateway entered FATAL state, too many start retries too quickly
```

**根因**：容器 `nofile` 只有 **1024**（`ulimit -n` 实测）。容器在 01:34 随宿主/daemon 事件重启后，
Envoy（concurrency=16）启动到 SDS secret manager 阶段申请文件描述符失败（EMFILE），
pilot-discovery 等其余进程不依赖该限额而正常存活 → 形成「控制面在、数据面没了」的分裂状态。

**修复方向（本指南只记录，不在此执行）**：

```bash
# 1) 提高文件描述符上限（二选一）
docker run ... --ulimit nofile=65536:65536 ...          # 启动参数
# 或 /etc/docker/daemon.json: "default-ulimits": {"nofile": {"Name": "nofile", "Hard": 65536, "Soft": 65536}}
# 2) 重启容器（或在容器内经正确的 supervisor socket 重新启动 gateway program）
docker restart higress
# 3) 验证：ps 见 envoy、ss 见 80、curl 18080 返回 404（空网关正常响应）
```

**方法论收获**：①「交互失败」不一定是网络问题，先确认双方进程都在（L1）；
② supervisord 管理的程序崩溃重试耗尽会进 **FATAL** 且不再自愈，查状态要看 `supervisord.log`；
③ 容器内一个组件的资源限额问题可以只杀死数据面，造成极具迷惑性的「半挂」状态。

### 2.6 高频故障模式库

**L1 进程层**

1. **EMFILE `too many open files`**：提高 nofile（见 2.5）。
2. **OOMKilled**：`describe pod` 见 `OOMKilled`，调大内存 limit 或降 concurrency；standalone 看 dmesg。
3. **启动即 exit 255**：gateway.log 最后一条 error 即原因（证书/端口占用/FD/bootstraps 生成失败）。
4. **FATAL 不重启**：supervisord `startretries`（默认 3）耗尽，需人工介入并先消除根因。

**L2 网络/证书层**

5. **xDS 端口不通**：K8s 中 controller Service/端点错误、gateway 配错 discoveryAddress；
   standalone 中 pilot 没起来或 loopback 被占。
6. **mTLS 失败**：`/etc/certs` 缺失/损坏/双方证书不匹配；重跑 initCerts 或重新部署。
   注意宿主时间异常也会导致证书校验失败。
7. **NetworkPolicy/防火墙**：K8s 限制 gateway → controller 15010/15012。

**L3 xDS 会话层**

8. **反复断连重连**：pilot 与 envoy 版本不匹配、gRPC keepalive/代理超时截断长连接
   （中间有四层代理时调大超时）。
9. **Envoy NACK**：pilot 日志 `Envoy XDS rejects` / `NACK`，error_detail 指明非法字段；
   多为 Envoy 版本旧、配置引用了不存在的资源（如 RDS 引用了没下发的 cluster）。
10. **只收到 LDS 没有 RDS/CDS**：ADS 顺序问题或配置在 controller 段缺失，做三段 configz 比对。

**L4 配置翻译层**

11. **Ingress 无反应**：缺 `ingressClassName: higress`，或 controller 未 watch 该 namespace。
12. **McpBridge/Nacos 源不通**：standalone/K8s 接 Nacos 时地址、namespace、group 错；
    Nacos 中服务名与 Ingress backend 对不上。
13. **CRD 没装/GVK 不识别**：`kubectl get crd` 核对；controller 日志 `no matches for kind`。
14. **Console 显示成功但实际没存住**：Console→apiserver/controller 链路报错，看 console.log 与 controller.log。

**L5 上游/流量层**

15. **503 no healthy upstream**：EDS 为空（服务发现没实例）或全部健康检查失败；
    `/clusters` 里看 endpoint 健康标记。
16. **404 但配置存在**：域名（Host 头）不匹配、路径前缀未 Strip、pathType 语义差异。
17. **上游 TLS 失败**：cluster 的 transport socket 未配 tls / SNI 不对。
18. **AI SSE 卡死**：插件或上游缓冲流式响应；确认插件不缓冲 body、超时按长连接设置。

**standalone 专属（本机历史踩坑）**

19. `docker cp` 是 merge 语义：不会删目标多余文件，旧路由会「复活」；收敛要显式 `rm`。
20. 容器访问宿主服务用网桥 IP（`172.17.0.1` 等），不是 `127.0.0.1`；
    K8s Pod 访问宿主用 `host.minikube.internal`。
21. xDS 生效有 10～15s 延迟，脚本必须轮询。

### 2.7 standalone ↔ K8s 常用命令对照

| 目的 | standalone | K8s（minikube） |
|---|---|---|
| 看组件状态 | `docker exec higress ps aux` | `kubectl -n higress-system get pods` |
| 看端口 | `docker exec higress ss -ltnp` | `kubectl -n higress-system get svc` |
| controller 日志 | `/var/log/higress/controller.log` | `kubectl -n higress-system logs deploy/higress-controller` |
| xDS server 日志 | `/var/log/higress/pilot.log` | 同上（controller Pod 内 pilot 容器） |
| gateway 日志 | `/var/log/higress/gateway.log` | `kubectl logs <gateway-pod> -c istio-proxy` |
| 重启组件 | 容器内 supervisorctl（注意实际 sock 路径） | `kubectl rollout restart deploy ...` / 删 Pod |
| 下发路由 | 写 `/data/{ingresses,services,endpoints}/*.yaml` | `kubectl apply -f route.yaml` |
| 列路由 | `docker exec higress ls /data/ingresses` | `kubectl get ingress` |
| 进环境 | `docker exec -it higress sh` | `kubectl -n higress-system exec -it <pod> -- sh` |

---

## Part 3 · Step-by-step 六周学习路线

> 每周 6～10 小时，原则：**先动手出结果，再回头补原理**；每周末必须完成「产出」和「验收问题」。

### 第 1 周：全景概念 + 跑通网关

- **读**：[Higress 是什么](https://higress.cn/docs/latest/overview/what-is-higress/)、[FAQ](https://higress.cn/docs/latest/overview/faq/)、本文 Part 1。
- **做**：
  1. 确认网关：`curl 127.0.0.1:18080`；打开 Console 18001。
  2. Console 手工建一条到 echo 上游的路由，curl 200，删除后 404。
  3. 观察 `gateway.log` 启动段与 `pilot.log` 的 push 日志，把日志和架构图对应起来。
- **产出**：一张手绘控制面/数据面/xDS 关系图。
- **验收**：能回答「控制面和数据面分别是什么」「xDS 解决什么问题」「为什么配置改了不用重启 Envoy」。

### 第 2 周：路由与流量治理基础

- **学**：路径匹配（pathType）、重写/重定向、超时、重试、CORS、Header 改写；Ingress 注解。
- **分清对象**：`Ingress`（标准）、`IngressRoute`（Higress/Istio 扩展）、`McpBridge`（服务来源）。
- **做**：用「路径路由 + Strip 前缀 + 超时重试」暴露一个 HTTP 服务；故意制造 404 并用 2.4 SOP 定位。
- **验收**：不看文档把任意 HTTP 服务经 Higress 暴露并 200；说清 404 的三种可能来源。

### 第 3 周：服务发现与上游治理

- **学**：静态 DNS 上游 vs Nacos（McpBridge）vs K8s Service；LB、健康检查、连接池、熔断（outlierDetection）。
- **做**：注册两个实例验证轮询；下线一个验证自动摘除（观察 EDS 与 503 变化）。
- **工具**：熟练使用 Envoy admin `/clusters`、`/stats`、pilot `/debug/connections`。
- **验收**：解释 503 `no healthy upstream` 时该按什么顺序查。

### 第 4 周：Wasm 插件体系

- **学**：[插件使用引导](https://higress.cn/docs/latest/plugins/intro/)；Go SDK 的
  `parse`/`requestHeaders`/`requestBody`/`responseHeaders` 阶段。
- **做**：
  1. 路由上绑 `cors` 和 `key-auth`，用 `curl -i` 对比。
  2. 跟做 [30 行写 Wasm Go 插件](https://higress.cn/blog/30-line-wasm/)：实现「带特定 Header 才放行 + 注入请求 ID」，热加载。
- **验收**：讲清插件在请求链路上的执行顺序、为什么认证插件放最前。

### 第 5 周：AI 网关（核心差异化）

- **学**：[AI 网关 Quick Start](https://higress.ai/docs/ai/quick-start/)、
  [AI Proxy 插件](https://higress.ai/docs/latest/user/plugins/ai/api-provider/ai-proxy/)、
  [多模型代理](https://higress.cn/docs/ai/scene-guide/multi-proxy)、
  [Token 限流](https://higress.cn/docs/ai/scene-guide/token-management)、语义缓存。
- **关键概念**：AI Proxy 统一 OpenAI 兼容入口；模型路由/fallback；真实 Provider Key 存网关侧；
  Token（而非请求数）维度限流。
- **做**：一个 `/v1/chat/completions` 入口挂两个模型（同一 key 的两个模型即可），验证：
  ① 普通应答 200；② **SSE 流式打字机不被缓冲**；③ 主模型失败 fallback；④ 网关 token 鉴权（调用方不碰真实 Key）。
- **结合本仓库**：跑 `spring-ai-demo`（Spring AI ReAct Agent + MCP），让它把 Higress 当 LLM 入口。
- **验收**：讲清 AI Proxy 如何隐藏真实 Key；指出 SSE 卡死该查哪几个地方。

### 第 6 周：可观测、生产化、读源码

- **学**：access log、Prometheus（Envoy `/stats/prometheus`）、Grafana、Tracing；
  TLS、HPA、金丝雀发布。
- **读源码**（[源码阅读指引](https://higress.cn/docs/latest/dev/code/)）：
  controller 中 Ingress→内部配置（`pkg/ingress/`）、WasmPlugin 转换、xDS server 入口。
  建议顺序：`pkg/ingress/config/ingress_config.go` → controller 启动 main → MCP server →
  对照 Istio `pilot-discovery` 的 xDS push。
- **做**：给路由配 v1/v2 灰度 90/10 + 指标看板（QPS/延迟/4xx/Token）。
- **验收**：从 metrics 找到任意一条路由的 QPS、错误率与 Token 消耗；能在源码里指出一条路由的转换位置。

### 练手项目阶梯（本仓库及相关项目）

1. 静态路由（多路径、前缀改写）→ 2. 多实例 LB/权重 → 3. key-auth + 限流压出 401/429
→ 4. 金丝雀 90/10 切 50/50 → 5. AI 统一入口 + fallback → 6. Prometheus + Grafana 闭环
→ 7. 自研 Wasm 插件。

> 本机可直接参考：`higress-ai-demo`（AI 全链路）、`scg-to-higress-migration`（治理规则迁移）、
> `scg-wso2-management`（最短：一条路由如何经 standalone 通道生效，建议先读）。

---

## Part 4 · 网上学习资料

### 官方（主线，优先读）

- 官网/文档（中文）：https://higress.cn/ ；新版文档站：https://higress.ai/
- [Higress 是什么](https://higress.cn/docs/latest/overview/what-is-higress/) ｜ [FAQ](https://higress.cn/docs/latest/overview/faq/)
- [Helm 云原生部署](https://higress.cn/docs/latest/ops/deploy-by-helm/) ｜ [Docker Compose 独立部署](https://higress.cn/docs/latest/ops/deploy-by-docker-compose/)
- [查看运行时配置（三段 debug）](https://higress.io/en/docs/latest/ops/how-tos/view-configs/)
- [插件使用引导](https://higress.cn/docs/latest/plugins/intro/) ｜ [Wasm 生效原理](https://higress.io/docs/latest/plugins/wasm-dev/wasm19/)
- AI 网关：[Quick Start](https://higress.ai/docs/ai/quick-start/) ｜
  [AI Proxy 插件](https://higress.ai/docs/latest/user/plugins/ai/api-provider/ai-proxy/) ｜
  [多模型代理](https://higress.cn/docs/ai/scene-guide/multi-proxy) ｜
  [Token 限流](https://higress.cn/docs/ai/scene-guide/token-management) ｜
  [语义缓存](https://higress.ai/en/docs/ai/scene-guide/semantic-cache)
- [源码阅读指引](https://higress.cn/docs/latest/dev/code/) ｜ [组件编译/架构说明](https://higress.cn/docs/latest/dev/architecture/)
- GitHub：https://github.com/alibaba/higress （samples、issues 是最好的故障案例库）
- 一键体验脚本：`curl -sS https://higress.cn/ai-gateway/install.sh | bash`

### 底层依赖（当字典查，不必通读）

- Envoy 官方文档：https://www.envoyproxy.io/docs/envoy/latest/（Architecture / Dynamic configuration(xDS) /
  HTTP connection manager / Admin）
- Envoy xDS REST 与 gRPC 协议：https://www.envoyproxy.io/docs/envoy/latest/api-docs/xds_protocol
- Istio 文档：https://istio.io/latest/docs/（Pilot、流量管理 CRD）
- Nacos：https://nacos.io/zh-cn/docs/what-is-nacos.html （服务发现/配置中心）
- K8s Ingress：https://kubernetes.io/docs/concepts/services-networking/ingress/ ；
  Gateway API：https://gateway-api.sigs.k8s.io/
- Higress Wasm Go SDK：https://github.com/alibaba/higress/plugins/wasm-go

### 博客 / 视频 / 社区

- 官方博客：https://higress.cn/blog/ （版本解读与落地实践，如
  [30 行 Wasm Go 插件](https://higress.cn/blog/30-line-wasm/)、[KubeCon 2023 分享](https://higress.cn/blog/2023-kubecon/)、
  [全局配置控制面原理](https://higress.cn/blog/configmap/)）
- 阿里云英文博客：[Beyond Nginx Ingress: Higress for the AI Era](https://www.alibabacloud.com/blog/beyond-nginx-ingress-higress-as-the-kubernetes-gateway-for-the-ai-era_603010)
- B 站/视频：搜索「Higress AI 网关」「Higress 源码」（官方账号有发布会与教程回放）
- 社区：GitHub Discussions/Issues、Higress 钉钉/微信社群（官网首页有二维码）、
  Stack Overflow 标签 `higress`
- 本地读书笔记：`bookspace/book_notes/notes_docs/blogs/ainotes/higress-gateway/higress-gateway.md`

**读法建议**：官方「Quick Start → 用户指南（路由/服务来源）→ 插件 → AI 网关」为主线通读；
Envoy/Istio 文档在排障中按术语反查；学习中每个概念都立刻在本机网关验证，比只看快得多。

---

## Part 5 · 入门自测清单

- [ ] 默画控制面/数据面/xDS 关系图并讲清三段配置链路（controller→pilot→envoy）
- [ ] 说清 LDS/RDS/CDS/EDS 各管什么、ADS 为什么要聚合到一条流
- [ ] 不看文档把一个 HTTP 服务经 Higress 暴露并 200，删除后 404
- [ ] 解释 NACK 是什么、去哪里看 error_detail
- [ ] 能用三段 debug 端点（8888 / 15014 / 15000）定位「配置在哪一段丢了」
- [ ] 503 `no healthy upstream` 能按顺序查到 endpoint 层
- [ ] 给路由加 key-auth + 限流并压出 401/429
- [ ] 配置 v1/v2 灰度并调整权重
- [ ] 讲清 AI Proxy 如何对调用方隐藏真实 Provider Key
- [ ] 验证 SSE 流式应答不被插件/网关缓冲
- [ ] 能看懂 Go Wasm 插件的请求/响应钩子并做小修改
- [ ] 从 Higress metrics 找到指定路由的 QPS、错误率、Token 消耗
- [ ] 能复述本机 0925「too many open files」故障的分层定位过程

勾到 8 个以上即跨过「会用」门槛，之后选一个方向深入：AI 网关 / 服务治理 / Wasm 插件开发。

---

## 附录 · 术语表

| 术语 | 含义 |
|---|---|
| Control Plane | 控制面：管理/下发配置，不转发业务流量（controller + pilot） |
| Data Plane | 数据面：实际转发请求（Envoy） |
| Envoy | C++ 高性能代理，Higress 的数据面内核 |
| pilot-discovery | Istio 的 xDS server，Higress 保留并复用 |
| pilot-agent | Envoy 守护进程：生成 bootstrap、拉起/监控 Envoy、提供 status 端口 |
| xDS | LDS/RDS/CDS/EDS 等发现协议的统称，gRPC 流式 |
| ADS | 聚合发现服务，多种 xDS 复用一条有序 gRPC 流 |
| SotW / Delta | 全量推送 / 增量推送两种 xDS 语义 |
| NACK | Envoy 拒绝下发配置时的否定应答，带错误详情 |
| Listener/Route/Cluster/Endpoint | Envoy 四件套：监听/路由规则/上游连接池/上游实例 |
| HCM | HTTP Connection Manager，Envoy 的 HTTP 过滤链核心 |
| McpBridge | Higress CRD：把 Nacos 等外部服务来源桥接进网关 |
| WasmPlugin | Higress/Istio 插件 CR，声明 Wasm 插件与配置 |
| SDS | Secret Discovery Service，证书/密钥下发（Envoy 0925 故障即崩在此处） |
| mTLS | 双向 TLS，xDS 控制面与数据面之间的认证方式 |
| all-in-one | standalone 单容器部署形态（supervisord 管理全部进程） |

---

*本文为 AI 辅助整理的学习与排障框架，架构细节结合本机实际部署与官方文档；
版本特性、端口与参数请以 Higress 官方最新文档为准。*
