# Higress 本地源码构建 + Minikube 完整集群 — 实施计划

> **For Hermes:** 按 Task 顺序执行，每完成一个 Task 做一次 git commit；破坏性操作（停容器、删数据、`minikube delete`）执行前必须再次确认；所有命令默认在 `~/IdeaProjects/agentspace/higress-ai-demo` 下执行。本计划是 `minikube-higress-cluster.md`（装发布镜像版）的**源码构建版**，两者二选一，互不覆盖。

**Goal:** 用 **Minikube（docker driver）** + **从源码打包的本地 Higress 镜像**（不再 pull 阿里云镜像）搭建完整 K8s Higress 集群，替换已停掉的 all-in-one `higress` 容器。对外端口保持 **18080/18443/18001 不变**。

**核心差异（vs 发布镜像版）：**
- 镜像全部本地构建：`higress/pilot`（controller/cp）+ `higress/proxyv2`（gateway/Envoy/dataplane）+ `higress-console/console`（Web UI）
- 用 `minikube image load` 注入本地镜像 → **Zero 外部镜像依赖**（内网友好）
- console 从源码出 `higress-console.jar`（前端 build 产物打进去）

---

## 📌 现状盘点（2026-09-17 实测）

| 项 | 现状 |
|---|---|
| 主机 | Linux，docker 29.2.1，24 核 / 46Gi 内存（可用 21Gi）/ 磁盘 346G 可用 |
| 代理 | `HTTP(S)_PROXY=127.0.0.1:7890`，GitHub raw 经代理 200 可达 |
| minikube | **未安装**（已确认）；kubectl / helm / make / jq 已有；**Go 未安装** |
| Java/Maven | openjdk 21.0.12；Maven `~/soft/maven/apache-maven-3.8.2`（国内代理 nonProxyHosts 已配，见 memory） |
| Node | v24.12.0（老前端构建可能需 `--openssl-legacy-provider`） |
| 目标镜像 | higress 主仓库 `higress-group/higress` **v2.2.4**；console `higress-group/higress-console` **v2.2.4** |
| 待替换容器 | `higress`（all-in-one）已 `docker stop`，端口 18080/18443/18001 已空，容器与数据卷保留可回滚 |
| Nacos | 独立容器 `nacos-standalone`（19080/8849/9849）仍在跑，HiMarket 共用 |

**镜像构成（v2.2.4）：**
| 产物 | 仓库 | 构建 |
|---|---|---|
| pilot | higress/pilot | Go（istio build 框架），`HUB/TAG` 控名 |
| proxyv2 | higress/proxyv2 | Go+Envoy 二进制（istio envoy 构建，最重） |
| console | higress-console/console | Java21 Maven + 前端 Node → `backend/Dockerfile` |

---

## ⚠️ 关键决策与坑（执行前必读）

### D1. 构建策略：纯源码全量 vs 混合
| 方案 | 内容 | 代价 | 结论 |
|---|---|---|---|
| **A 混合（默认）** | **pilot + console 全源码**；**proxyv2 拉发行镜像**（Envoy 编译最重、最容易翻车） | 轻，风险低 | ✅ 默认 |
| B 全源码 | 三个都 `make docker-build` | proxyv2 需编译注入版 Envoy，本地无工具链，小时级且易失败 | 备选 |

### D2. 版本与构建框架
- higress 用 Istio 式 Makefile（`Makefile.core.mk`）；镜像目标 `make docker-build`（`HUB=localhost/higress TAG=v2.2.4`）。**执行时先 `make help` 或 `grep -E '^[a-z].*:' Makefile.core.mk` 核对确切 target 名**，再跑。
- **Go 未安装**：minikube docker driver 下 Istio build 优先走容器构建（`BUILD_WITH_CONTAINER=1`），仍需本地有 go 环境做 init/校验 → **先装 Go 1.23+ 到 `~/go/bin`（tarball，无 sudo）**。
- console 版本必须对齐 higress 主版本（v2.2.4 对应 console v2.2.4，由根目录 `DEP_VERSION` 决定）。

### D3. console 构建链条（最易踩）
```
frontend npm build  ← Node24 老前端可能要 --openssl-legacy-provider
        │ 产物打进
backend  mvn package  → console/target/higress-console.jar
        │ COPY 进
backend/Dockerfile  (eclipse-temurin:21-jdk, EXPOSE 8080)
```
- **坑 A**：`backend/Dockerfile@v2.2.4` 依赖 `COPY tools/mcp/${TARGETARCH}/main`（预编译 Go 二进制），但 **v2.2.4 tag 无 `tools/mcp` 目录、只有 main 分支有**。三个处置：
  1. （推荐）构建时自己编 mcp：`cd $(mktemp) && go build` 出两个文件放 `tools/mcp/{linux-amd64,linux-arm64}/main`（mcp 源码在 higress 仓库 `tools/...`），或
  2. 直接 `docker buildx build --platform linux/amd64` 时用 `--target` 跳过，或
  3. 用 main 分支构建 console（版本略超前）。
  计划采用 **1**，并在 Task 构建 console 前先定位 mcp 源码位置再决定。
- **坑 B**：Node24 构建老前端 `ERR_OSSL_EVP_UNSUPPORTED` → 加 `NODE_OPTIONS=--openssl-legacy-provider`。
- **坑 C**：Maven 国内代理参照 memory（settings.xml 配 nonProxyHosts，勿在 MAVEN_OPTS 再设 JVM 代理）。

### D4. 部署策略（minikube image load + helm 本地 values）
- 本地镜像 tag 用 `localhost:5000/higress/pilot:v2.2.4` 等（buildx 需存在且可解析），或直接 `higress/pilot:v2.2.4` 加 **imagePullPolicy: Never** 天然走本地。**计划采用：构建 tag = 本地名，`minikube image load`，values 里 `image.pullPolicy: IfNotPresent` + 显式 `image.repository/tag`。**
- helm chart 来源：higress group 的 `helm/higress.tar.gz` 或 `https://higress.cn/helm-charts`。**`helm show values` 先核对键名**（本项目 helm 路径都在仓库 `helm/` 下）。
- **不启用 o11y**：`global.o11y.enabled=false`；内置 Nacos `global.local=true`。
- **不用 alias Higress Ingress**（minikube ingress 插件），避免 init-controller 抢；`--ports` 映射 NodePort。

### D5. 端口与网络
- minikube `--ports=18080:30080 --ports=18443:30443 --ports=18001:30001`。
- Pod → 宿主 upstream：`host.minikube.internal`；宿主/容器 → 网关：`127.0.0.1:18080`（网桥内容器走 `172.17.0.1:18080`）。
- **443 被 tailscaled 占用** → 只映射 18443，不碰 443。

---

## Task 分解

### Task 0 — 环境准备：Go 工具链 + 源码拉取（只读/装工具）
- [ ] 装 Go 1.23+ 至 `~/go`（无 sudo）：`curl -L https://go.dev/dl/go1.23.x.linux-amd64.tar.gz | tar -C ~ -xzf -`；导出 `PATH=$HOME/go/bin:$PATH` `GOPATH=$HOME/go`（写入 shell rc 或本项目 `infra/minikube/.envrc`）
- [ ] clone（镜像代理）：
  ```bash
  cd ~/IdeaProjects/agentspace
  git clone --depth 1 --branch v2.2.4 https://github.com/higress-group/higress.git
  git clone --depth 1 --branch v2.2.4 https://github.com/higress-group/higress-console.git
  ```
- [ ] `go version`、`make --version`、`~/soft/maven/bin/mvn -v` 全通过
- ✅ 检查点：两仓库在 v2.2.4，go/make/mvn 可执行

### Task 1 — 安装 Minikube（docker driver，无 sudo）
- [ ] 经代理下载 minikube 到 `~/bin/minikube`（选稳定版）
- [ ] `minikube start --driver=docker --cpus=6 --memory=8192 --disk-size=60g \
       --ports=18080:30080 --ports=18443:30443 --ports=18001:30001 \
       --image-mirror-country=cn`（若拉 k8s 组件镜像慢再补国内 mirror 配置）
- [ ] 验证 containerd 能拉到 minikube 基础镜像；`minikube addons list`（**不开** ingress 插件）
- ✅ 检查点：`kubectl get nodes` Ready；`minikube ip` 可达；`ss -ltn` 出现 30080/30443/30001

### Task 2 — 构建 Higress 核心镜像（pilot，源码）
- [ ] 进 `higress/` 仓库：`make help` / grep `Makefile.core.mk` 定位 `docker-build` 与 `HUB/TAG` 变量
- [ ] 本地构建：`make docker-build HUB=higress TAG=v2.2.4`（产物 `higress/pilot:v2.2.4`；proxyv2 若走方案 A 从发行镜像 pull）
- [ ] `minikube image load higress/pilot:v2.2.4`（体积大，留足时间）
- [ ] 记录构建 log 到 `infra/minikube/logs/core-build.log`
- ✅ 检查点：`minikube image list | grep higress` 含 pilot；镜像 tag 正确

### Task 3 — 构建 Higress Console 镜像（Java+前端源码）
- [ ] 定位 mcp 源码（higress 仓库 `tools/` 下 find），按 **D3-A** 自编 `tools/mcp/{linux-amd64,linux-arm64}/main` 放进 console 仓库 `tools/mcp/`
- [ ] `cd higress-console/frontend && npm install && npm run build`（如遇 SSL 报错加 `NODE_OPTIONS=--openssl-legacy-provider`）
- [ ] 按 console 仓库说明把前端 build 产物并入后端（或使用仓库根 make 脚本，若存在）
- [ ] `cd backend && mvn clean package`（用 `~/soft/maven`，代理配置文件位）

  产出：`backend/console/target/higress-console.jar`
- [ ] `docker build -f backend/Dockerfile -t higress-console/console:v2.2.4 .`（在 `higress-console/` 根，`--build-arg` 正确给 TARGETARCH）
- [ ] `minikube image load higress-console/console:v2.2.4`
- ✅ 检查点：java -jar 冒烟 `console/target/higress-console.jar --config ... start` 能起；`minikube image list` 含 console

### Task 4 — Helm 部署 Higress 集群（用本地镜像）
- [ ] helm repo / 用仓库内 chart：`helm show values` 先核对 `global.local`、`o11y.enabled`、gateway/console `service.type=NodePort` + `nodePort`、`image.repository/tag/pullPolicy` 键名
- [ ] 写 `infra/minikube/higress-values.yaml`：local=true、o11y=false、NodePort 30080/30443/30001、所有 image 指向本地 tag + `pullPolicy: IfNotPresent`（proxyv2 若方案 A pull 发行镜像则 keep）
- [ ] 安装：
  ```bash
  helm install higress -n higress-system --create-namespace \
    -f infra/minikube/higress-values.yaml higress.io/higress
  ```
- [ ] `kubectl -n higress-system get pods` 等全 Running（controller / gateway / console / 内置 nacos）
- ✅ 检查点：pods Running；`helm list -n higress-system` deployed

### Task 5 — 端口与入口验证
- [ ] `curl http://127.0.0.1:18080` → 404（空网关正常响应）
- [ ] Console `http://127.0.0.1:18001` 可登录、可见菜单
- [ ] HTTPS `18443` 自签监听正常
- [ ] Console 手工建一条 echo 测试路由 → 18080 返回 200 → 删除 → 404
- ✅ 检查点：三端口行为与旧环境一致；截图/记录存 `infra/minikube/evidence/`

### Task 6 — 数据面链路验证（宿主 downstream 可达）
- [ ] `wso2-demo-downstream:9081` 在跑；临时 test Pod 验证 `curl host.minikube.internal:9081/healthz`
- [ ] 写 Ingress + Service + Endpoints 指向 `host.minikube.internal:9081`
- [ ] `kubectl apply -f` → 等 xDS 生效（~10s）→ `curl 127.0.0.1:18080/demo/time` 200 → 删除 404
- ✅ 检查点：增/删收敛各一次，证据存 `infra/minikube/evidence/task6.txt`

### Task 7 — wso2 adapter 切 kubectl 通道（二期，可延后）
- [ ] 生成 minikube kubeconfig；adapter `channel: kubectl`；Endpoints host 改 `host.minikube.internal`
- [ ] E2E：WSO2 发 2 API → SCG 200 + minikube Higress 200；下线双 404
- 🟡 检查点：wso2 项目在新集群 E2E 通过

### Task 8 — 文档与固化（可选体验目标）
- [ ] `infra/minikube/` 放 `up.sh` / `down.sh` / `reset.sh` / `values`
- [ ] 更新 README 为「Minikube + 源码镜像」环境
- ✅ 检查点：新人可照文档 30 分钟重建

---

## 验收矩阵（Done 定义）
| # | 验收项 | 期望 |
|---|---|---|
| 1 | `kubectl -n higress-system get pods` | controller/gateway/console/nacos 全 Running |
| 2 | 镜像来源 | 全部本地构建/`image load`，日志无外部 429 |
| 3 | Console `127.0.0.1:18001` | 可登录、可配路由 |
| 4 | demo 路由增删 | 18080 上 200 → 404 |
| 5 | Pod→宿主 upstream | 9081 经 `host.minikube.internal` 可达 |
| 6 | 旧容器 | `higress` stopped 保留，`docker start` 可回滚 |
| 7 | 重启保持 | `minikube stop && start` 后路由与端口自恢复 |

## 风险清单
| 风险 | 等级 | 缓解 |
|---|---|---|
| proxyv2 源码编译重/失败 | 高 | 默认走方案 A（混合），pilot+console 源码、proxyv2 拉发行 |
| console `tools/mcp` tag 缺失 | 高 | D3-A 自编 mcp，进构建前先定位源码 |
| Node24 老前端构建 | 中 | `--openssl-legacy-provider` |
| Go 工具链缺失 | 中 | Task 0 先装 |
| Helm chart 键名差异 | 中 | `helm show values` 先核对 |
| minikube 镜像拉取慢 | 中 | 国内 mirror + 本地 image load（核心零外拉） |
| 每次全量编译耗时 | 中 | pilot 增量、console 仅 Java；可拆 Task 分开跑 |
| **本次破坏动作集** | - | 停容器（已做）、`minikube delete`（预留，先 `docker start higress` 保障）|

## 明确不做
- ❌ 不做 proxyv2 全源码（Envoy 编译）——除非用户明确要
- ❌ 不把 HiMarket 7 容器迁进 K8s
- ❌ 不启用 o11y（prometheus/grafana/skywalking），跑通后二期
- ❌ 不动 Tailscale Funnel / nginx / 宿主 443
- ❌ 不删旧容器与 `~/himarket-data` 卷

## 预估
- Task 0–1：30–45min（Go + minikube + 镜像拉取）
- Task 2–3：1.5–2.5h（pilot 编译 + console Java/前端；最大不确定性在 mcp 补建）
- Task 4–6：1h
- Task 7–8：1h 可选
- **合计约半天**；可分段 commit，随时可回滚（`docker start higress`）。