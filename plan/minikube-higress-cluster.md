# Higress 迁移到 Minikube 完整集群 — 实施计划

> **For Hermes:** 按 Task 顺序执行，每完成一个 Task 做一次 git commit；破坏性操作（停容器、删数据）执行前必须再次确认；所有命令默认在 `~/IdeaProjects/agentspace/higress-ai-demo` 下执行。

**Goal:** 用 **Minikube + Helm 部署的完整 Higress K8s 集群**替换当前随 HiMarket 运行的
`higress` all-in-one 单容器，使 higress-ai-demo 拥有「真 K8s 控制面（Deployment/Ingress/CRD/xDS）」
的标准实验环境，端口与对外行为保持 **18080/18443/18001 不变**。

**Architecture（迁移后）：**

```
宿主 (Linux, docker 29)
├── minikube (docker driver, 真 K8s 单节点)
│   └── namespace higress-system
│       ├── higress-controller (Deployment)   ← 监听 Ingress/CRD → xDS
│       ├── higress-gateway (Pod, Envoy 80/443)
│       ├── higress-console (Deployment)
│       └── 内置 Nacos (global.local=true, Standalone 模式)
├── 宿主端口 18080/18443/18001 ── minikube NodePort 映射
├── wso2-demo-downstream 容器 :9081 (宿主可达, Pod 经 host.minikube.internal 访问)
└── himarket 其余 7 容器保留(higress 容器已停)
```

**Tech Stack:**
- Minikube（docker driver，**无需 sudo**）、kubectl v1.36（已有）、helm v3.16（已有）
- Higress Helm Chart（`https://higress.cn/helm-charts`，已验证经代理 200 可达）
- `global.local=true`（Standalone，内置 Nacos）、`global.o11y.enabled=false`（先不开可观测组件）
- 镜像源：`higress-registry.cn-hangzhou.cr.aliyuncs.com`（本机已验证可用）

---

## 📌 现状盘点（2026-09-17 实测）

| 项 | 现状 |
|---|---|
| 现有网关 | 容器 `higress`，镜像 `higress/all-in-one:latest`，HiMarket `install.sh` 拉起 |
| 网络 | `docker_himarket-network`（172.18.0.8） |
| 端口 | 宿主 **18001** Console / **18080** HTTP / **18443** HTTPS |
| 数据卷 | `~/himarket-data/data/higress → /data`（含 ingresses/services/endpoints YAML） |
| 进程构成 | supervisord + apiserver + pilot-discovery + pilot-agent + envoy + console(java) + nginx |
| Nacos | **独立容器** `nacos-standalone`（Nacos v3.2.1，宿主 19080/8849/9849），HiMarket 共用 |
| HiMarket 容器 | himarket-server/admin/frontend + sandbox-shared + mysql + redis + nacos 共 7 个保留 |
| minikube | **未安装**；kubectl/helm 已装；`/dev/kvm` 存在；24 核 / 346G 磁盘可用 |
| 443 端口 | 被 tailscaled（Funnel）占用 → 新集群不得抢宿主 443 |

**现有 `/data/ingresses` 中的路由**（迁移时需在新集群重建）：

- `default.yaml`（HiMarket Console 自身路由，系统级）
- `wso2-demo-echo.yaml`、`wso2-demo-time.yaml`（scg-wso2-management 项目下发）
- 可能还有 HiMarket 发布的 MCP/AI 路由（执行 Task 0 时完整导出核对）

---

## ⚠️ 影响面与关键决策（执行前必读）

### 1. 「关闭现有 higress」影响三个消费者

| 消费者 | 影响 | 本计划处理 |
|---|---|---|
| **HiMarket**（server/admin/frontend） | 网关管理、产品/MCP 发布、沙箱预览依赖 Higress，停容器后这些功能不可用；其配置写死 compose 网络内主机名，无法直接指向新集群 | 其余 7 容器**保留运行**；HiMarket 与新集群的深度整合不在本期（见「未做事项」） |
| **scg-wso2-management** | adapter 的 HigressSink 走 `docker cp` 投递到该容器 `/data`，通道失效 | Task 7 切到 **kubectl 通道**（代码已预留 `channel: kubectl`），用 kubeconfig apply 标准 Ingress |
| **higress-ai-demo 本身** | 目标服务，新集群即其标准网关 | 全部实验在新集群重做/验证 |

> 「关闭」= `docker stop higress`（**保留容器与数据卷，随时可 `docker start` 回滚**），不做 rm。

### 2. 端口策略：保持 18080/18443/18001 不变

这样现有脚本、curl 示例、wso2 adapter 配置都不用换地址。实现方式：
Helm 把 gateway/console Service 固定为 **NodePort 30080/30443/30001**，
`minikube start --ports` 把宿主 18080/18443/18001 映射到这些 NodePort。

### 3. Minikube driver 选择：docker（不选 KVM2）

| driver | sudo 需求 | 结论 |
|---|---|---|
| docker | 无（用户已在 docker 组） | ✅ 采用，仍是完整 K8s（etcd/APIServer/kubelet 全有） |
| KVM2 | 需安装 libvirt driver + 用户组，可能要 sudo | 备用 |

### 4. 网络连通（迁移后最容易踩的坑）

- 宿主/其它容器 → 网关：`127.0.0.1:18080`（minikube 端口映射）
- Docker 网络内容器（himarket/wso2-demo-*）→ 网关：走网桥 IP `172.17.0.1:18080`
- **Pod → 宿主上的 downstream:9081**：用 `host.minikube.internal`（minikube 自动注入），
  Service/Endpoints 里写该主机名；不再用旧的 `172.17.0.1`（Pod 网络视角不同）

---

## Task 分解

### Task 0 — 备份与导出（只读，无破坏）
- [ ] 导出旧容器全部路由配置：`docker cp higress:/data ./infra/minikube/backup-data`，清点 ingresses/services/endpoints
- [ ] 记录旧容器镜像、网络、env：`docker inspect higress > backup/inspect.json`
- [ ] 记录 18080 当前路由清单（curl 逐个探测，形成迁移对照表）
- [ ] 确认 wso2 adapter 当前下发的路由名与 Higress console 中现有 AI/MCP 路由
- ✅ 检查点：`backup-data/` 完整入库（gitignore 大文件，仅留清单 manifest）

### Task 1 — 安装 Minikube（docker driver，无 sudo）
- [ ] 经代理下载 minikube 二进制到 `~/bin/minikube`（选稳定版）
- [ ] `minikube start --driver=docker --cpus=6 --memory=8192 --disk-size=60g \
       --ports=18080:30080 --ports=18443:30443 --ports=18001:30001 \
       --image-repository=<国内 K8s 镜像 mirror>`
- [ ] 配置 containerd 镜像加速（若 Higress 依赖 docker.io 镜像，验证拉取）
- [ ] `kubectl get nodes` Ready；`minikube addons list`（默认不加 ingress 插件，避免与 Higress 冲突）
- ✅ 检查点：节点 Ready，`minikube ip` 可达，宿主 `ss -ltn` 能看到映射规划端口

### Task 2 — Helm 安装完整 Higress 集群
- [ ] `helm repo add higress.io https://higress.cn/helm-charts`（经代理）
- [ ] 编写 `infra/minikube/higress-values.yaml`：
  - `global.local=true`、`global.o11y.enabled=false`
  - gateway Service `type=NodePort`，HTTP nodePort **30080**、HTTPS **30443**
  - console Service `type=NodePort`，nodePort **30001**
  - 镜像仓库显式指定 `higress-registry.cn-hangzhou.cr.aliyuncs.com`
  - 控制台初始管理员凭据用环境变量/secret 注入（**不复用弱口令**，记入本机密码文件，不入库）
- [ ] 执行用户给定安装命令 + values：
  ```bash
  helm install higress -n higress-system higress.io/higress --create-namespace \
    --render-subchart-notes -f infra/minikube/higress-values.yaml \
    --set global.local=true --set global.o11y.enabled=false
  ```
- [ ] 等待全部 Pod Ready（controller / gateway / console / 内置 nacos）
- ✅ 检查点：`kubectl -n higress-system get pods` 全 Running；`helm list -n higress-system` deployed

### Task 3 — 端口与入口验证
- [ ] 验证宿主 `http://127.0.0.1:18080` 返回 404（空网关正常响应，非连接拒绝）
- [ ] Console `http://127.0.0.1:18001` 可登录，看到路由/域名/服务来源/插件菜单
- [ ] HTTPS 18443 监听正常（自签）
- [ ] 在 Console 手工建一条测试路由（echo 上游），200 后删除，确认 UI→xDS 链路通
- ✅ 检查点：三端口行为与旧环境一致；截图/记录存 `evidence/`

### Task 4 — 关闭旧 Higress 容器（首个破坏性动作）
- [ ] 前置：Task 0 备份完成、Task 2/3 新集群健康
- [ ] `docker stop higress`（不 rm）；确认 18080/18443/18001 由 minikube 映射接管，`ss -ltn` 无端口冲突
- [ ] 观察 himarket-server 日志确认影响范围（预期网关相关功能报错，其余正常）
- [ ] 记录回滚命令：`docker start higress` + 停 minikube 端口映射
- ✅ 检查点：新集群独占三端口；旧容器 `docker ps -a` 可见、可一键回滚

### Task 5 — 数据面链路：第一条真实路由
- [ ] 确认 wso2-demo-downstream:9081 在跑；Pod 内验证 `curl host.minikube.internal:9081/healthz` 可达
  （用临时 test Pod：`kubectl run nettest --image=... --rm -it -- sh`）
- [ ] 写 `manifests/01-demo-upstream.yaml`：Ingress（ingressClassName: higress）
  + Service（externalName 或 ClusterIP）+ Endpoints 指向 `host.minikube.internal:9081`
- [ ] `kubectl apply -f`，等 xDS 生效（~10s）
- [ ] `curl 127.0.0.1:18080/demo/time` → 200；删除路由 → 404
- ✅ 检查点：增/删收敛各一次，证据存 `evidence/task5-k8s-route.txt`

### Task 6 — 路由资产迁移
- [ ] 将 Task 0 导出的用户路由逐个改写为 K8s manifest 放 `manifests/`（命名空间 higress-system）
- [ ] 系统路由 `default.yaml` **不迁**（那是旧 all-in-one console 专用）
- [ ] 与用户逐条确认哪些 HiMarket AI/MCP 路由需要在新集群重建（无上游的不迁）
- 🟡 检查点：用户确认迁移清单；全部应用后 Console 列表与旧清单对照一致

### Task 7 — scg-wso2-management adapter 切换 kubectl 通道
- [ ] 生成专用 kubeconfig（`kubectl config view --minify --flatten`，指向 minikube）
- [ ] adapter 配置改 `channel: kubectl`、`kubeconfig:` 指向该文件；Endpoints host 改 `host.minikube.internal`
- [ ] 跑 `sync`：创建/更新走 `kubectl apply`，删除改为 annotate 或 apply 空列表策略
  （注意：K8s 通道当前 sink 代码只有 apply 没有 delete，需补 `kubectl delete` 收敛逻辑）
- [ ] E2E：WSO2 发布 2 API → SCG 200 + **minikube Higress 200**；下线 → 双 404
- ✅ 检查点：wso2 项目 E2E 在新集群通过，docker 零依赖

### Task 8 — AI 网关主线验证（higress-ai-demo 的核心）
- [ ] 配置 AI Proxy/AI Route（或先 key-auth + 普通 LLM 上游），复用 spring-ai-demo 的 Ark 上游
- [ ] 至少验证一个 AI 插件链路：统一 OpenAI 入口 → 模型路由 → SSE 流式返回不被缓冲
- [ ] MCP 路由按需验证（himarket 托管的 MCP 若停服，用 mcp-servers/ 下的本地 server 兜底）
- ✅ 检查点：`curl` SSE 流式 chat 完成；记录插件配置到 `infra/minikube/ai-route-example.yaml`

### Task 9 — 文档、固化、提交
- [ ] 更新 README：环境从「HiMarket all-in-one」改为「Minikube 完整集群」，新快速开始
- [ ] `infra/minikube/` 放：values、启动/停止/重置脚本（`up.sh`/`down.sh`）、manifest 样例
- [ ] 写「日常操作」：minikube start/stop、helm upgrade、看日志、重置集群
- [ ] 本机敏感信息（console 密码、kubeconfig）不入 git
- [ ] 全部 Task 提交推送 `teaho-infra/higress-ai-demo`

---

## 验收矩阵（Done 定义）

| # | 验收项 | 期望 |
|---|---|---|
| 1 | `kubectl -n higress-system get pods` | controller/gateway/console/nacos 全 Running |
| 2 | Console `127.0.0.1:18001` | 可登录、可配路由 |
| 3 | demo 路由增删 | 18080 上 200 → 404 收敛 |
| 4 | 旧 higress 容器 | stopped 但保留，`docker start` 可回滚 |
| 5 | wso2 adapter E2E | 双网关（SCG + minikube Higress）发布 200/下线 404 |
| 6 | AI 路由 | OpenAI 兼容入口 + SSE 流式 200 |
| 7 | 重启保持 | `minikube stop && minikube start` 后路由与端口自动恢复 |
| 8 | 文档 | README + 脚本 + values 齐全，新人按文档 30 分钟内重建 |

## 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| minikube docker driver NodePort 宿主映射行为差异 | 中 | Task 1/3 先验证；备选 `minikube tunnel`（docker driver 下免 sudo）或 `kubectl port-forward` |
| K8s 镜像拉取慢/429（docker.io） | 中 | 全部显式指定阿里云 higress-registry；minikube image mirror；必要时 `minikube image load` |
| Pod → 宿主 upstream 不通 | 中 | Task 5 先做 nettest 探测；`host.minikube.internal` + 宿主防火墙 |
| 停旧容器影响 himarket 演示 | 中 | 只 stop 不 rm；明确告知；回滚一条命令 |
| Higress chart 版本/values 键名差异 | 低 | `helm show values` 先核对再写 values；小步 install |
| minikube 占资源（8G/6CPU） | 低 | 24 核大内存机器；不用时 `minikube stop` 释放 |
| 443 冲突 | 已规避 | 新集群只映射宿主 18443，不碰 443 |

## 明确不做（IN/OUT）

- ❌ 不把 HiMarket 7 容器迁进 K8s（本期只换网关；HiMarket→新集群深度整合是后续独立项目）
- ❌ 不删除旧容器和 `~/himarket-data` 数据卷（保留回滚能力，观察一段时间后再清理）
- ❌ 不启用 o11y 可观测组件（prometheus/grafana/skywalking），跑通后作为二期
- ❌ 不动 Tailscale Funnel / nginx（网关端口不变，代理层零改动）
- ❌ 不做多节点集群、不做生产化（TLS 证书、HPA、高可用）

## 预估

- Task 0–3：约 1.5–2h（主要在镜像拉取）
- Task 4–6：约 1h
- Task 7–8：约 1.5h（含 adapter 补 delete 逻辑）
- Task 9：0.5h
- **合计约半天**；最大不确定性是 minikube 镜像网络与 NodePort 映射。
