# Higress 本地源码构建 + Minikube 完整集群 — 实施计划

> **For Hermes:** 按 Task 顺序执行，每完成一个 Task 做一次 git commit；破坏性操作（停容器、删数据、`minikube delete`）执行前必须再次确认；所有命令默认在 `~/IdeaProjects/agentspace/higress-ai-demo` 下执行。本计划是 `minikube-higress-cluster.md`（装发布镜像版）的**源码构建版**，两者二选一，互不覆盖。

**Goal:** 用 **Minikube（docker driver）** + **从源码打包的本地 Higress 镜像**（不再 pull 阿里云镜像）搭建完整 K8s Higress 集群，替换已停掉的 all-in-one `higress` 容器。对外端口保持 **18080/18443/18001 不变**。

**核心差异（vs 发布镜像版）：**
- 镜像全部本地构建：`higress/higress`（controller/cp）+ `higress/proxyv2`（gateway/Envoy/dataplane）+ `higress-console/console`（Web UI）
- 用 `minikube image load` 注入本地镜像 → **Zero 外部镜像依赖**（内网友好）
- console 从源码出 `higress-console.jar`（前端 build 产物打进去）

---

## 📌 现状盘点（2026-09-17 实测）

| 项 | 现状 |
|---|---|
| 主机 | Linux，docker 29.2.1，24 核 / 46Gi 内存（可用 21Gi）/ 磁盘 346G 可用 |
| 代理 | `HTTP(S)_PROXY=127.0.0.1:7890`，GitHub raw 经代理 200 可达 |
| minikube | **未安装**（已确认）；kubectl / helm / make / jq 已有；**Go 未安装** |
| Java/Maven | openjdk 21.0.12；console 走仓库内 **Maven Wrapper（`./mvnw`）**，无需系统 Maven |
| Node | v24.12.0（老前端构建可能需 `--openssl-legacy-provider`） |
| 目标镜像 | higress 主仓库 `higress-group/higress` **v2.2.4**；console `higress-group/higress-console` **v2.2.4** |
| 待替换容器 | `higress`（all-in-one）已 `docker stop`，端口 18080/18443/18001 已空，容器与数据卷保留可回滚 |
| Nacos | 独立容器 `nacos-standalone`（19080/8849/9849）仍在跑，HiMarket 共用 |

**镜像构成（v2.2.4，已在源码/tag/values 验证）：**
| 产物 | 仓库中镜像名 | 构建 | helm 位置 |
|---|---|---|---|
| gateway(dataplane) | `proxyv2`（含 proxy_init） | Go+Envoy（istio envoy 构建，最重） | `helm/core` |
| controller(cp) | `higress` | Go（`docker-build`=docker.higress） | `helm/core` |
| console(Web) | `higress-console/console` | `backend/build.sh`（Maven Wrapper `./mvnw` + 前端 Node） | `higress-console/helm` |

**Helm 实为两个 chart**（主集群 + console），镜像 tag/HUB 用 `global.hub`/`controller.tag` 等覆盖。

**console Dockerfile 依赖 `tools/mcp/<arch>/main`（Go 预编译二进制），但 v2.2.4 tag 无该目录（仅 main 分支有）** → 本计划**不用 v2.2.4 的 backend/Dockerfile 直接构建**，改用 `backend/build.sh`（脚本内 docker 命令注释掉）出 jar，再套一层最小 Dockerfile（FROM temurin:21-jdk + COPY jar + start.sh），从根上绕开 mcp COPY 缺失。若要保留 mcp 能力再从 main 分支取二进制补入。

---

## ⚠️ 关键决策与坑（执行前必读）

### D1. 构建策略：纯源码全量 vs 混合
| 方案 | 内容 | 代价 | 结论 |
|---|---|---|---|
| **A 混合（默认）** | **controller + console 全源码**；**gateway(proxyv2) 拉发行镜像**（Envoy 编译最重、最容易翻车） | 轻，风险低 | ✅ 默认 |
| B 全源码 | 三个都 `make docker-build` | proxyv2 需编译注入版 Envoy，本地无工具链，小时级且易失败 | 备选 |

### D2. 版本与构建框架（已实测）
- higress 用 Istio 式 Makefile（`Makefile.core.mk`@v2.2.4）；镜像目标：`docker-build`=docker.higress（→ controller 镜像 `higress`）、`docker.proxyv2` 独立且最重。**执行时先 `make help` / `grep -E '^[a-z].*:' Makefile.core.mk` 核对确切 target 名**。
- **Go 未装** → Task 0 先装 Go 1.23+ 到 `~/go`（tarball 无 sudo）；Istio 构建优先容器模式但仍需本地 go 做 init/校验。

### D3. console 构建链（最易踩，已实测修正）
```
frontend npm build  ← Node24 老前端加 NODE_OPTIONS=--openssl-legacy-provider
        │ build 产物打进
backend ./mvnw package（Maven Wrapper，非系统 maven）  → console/target/higress-console.jar
        │ 用 backend/build.sh 一键（脚本内 docker 命令可注释）
后端 jar + start.sh → 自定义最小 Dockerfile（temurin:21-jdk）→ 镜像
```
- **坑 A（已证明）**：官方 `backend/Dockerfile@v2.2.4` 依赖 `COPY tools/mcp/${TARGETARCH}/main`，但 **v2.2.4 tag 无 `tools/mcp`（仅 main 分支有）**，直接构建会因缺文件失败 → **改用 `backend/build.sh` 出 jar + 自定义 Dockerfile** 绕开；要 mcp 再从 main 分支取二进制补入。
- **坑 B**：Node24 构建老前端 `ERR_OSSL_EVP_UNSUPPORTED` → 加 `NODE_OPTIONS=--openssl-legacy-provider`。
- **坑 C**：Maven Wrapper 首次会下 maven 本体，走 `~/.m2`；如慢再配 `settings.xml` nonProxyHosts。

### D4. 部署策略（minikube image load + helm 本地 values，已实测为双 chart）
- 本地镜像 tag 直接用本地名（如 `higress/higress:v2.2.4`、`higress/proxyv2:v2.2.4`、`higress-console/console:v2.2.4`）+ `imagePullPolicy: IfNotPresent` + `minikube image load` 天然走本地。
- **chart 是两个**：主集群 `helm/core`（gateway/controller/内置 nacos，镜像键在 `values.yaml`：`gateway.image`、`controller.image`、`global.hub/tag`，proxyv2 走 `global.hub`，默认 `proxyv2`/`higress`/`gateway`）；console 用 `higress-console/helm`（独立 chart，镜像 `higress-console/console`）。
- 先 `helm show values` 核对键名（含 `global.local`、`o11y.enabled`、`service.type=NodePort` + `nodePort`、`image.pullPolicy`）。
- **不启用 o11y**：`global.o11y.enabled=false`（values 中默认已是 false）；内置 Nacos `global.local=true`。

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
- [ ] `go version`、`make --version` 通过（console 用 `./mvnw`，无需系统 maven）
- ✅ 检查点：两仓库在 v2.2.4，go/make 可执行

### Task 1 — 安装 Minikube（docker driver，无 sudo）
- [ ] 经代理下载 minikube 到 `~/bin/minikube`（选稳定版）
- [ ] `minikube start --driver=docker --cpus=6 --memory=8192 --disk-size=60g \
       --ports=18080:30080 --ports=18443:30443 --ports=18001:30001 \
       --image-mirror-country=cn`（若拉 k8s 组件镜像慢再补国内 mirror 配置）
- [ ] 验证 containerd 能拉到 minikube 基础镜像；`minikube addons list`（**不开** ingress 插件）
- ✅ 检查点：`kubectl get nodes` Ready；`minikube ip` 可达；`ss -ltn` 出现 30080/30443/30001

### Task 2 — 构建 Higress controller 镜像（Go 源码）
- [ ] 进 `higress/` 仓库 root：`make help` / `grep -E '^[a-z].*:' Makefile.core.mk` 定位 `docker-build`（=`docker.higress`，出 controller 镜像 `higress`）与 `HUB/TAG` 变量
- [ ] 本地构建 controller：`make docker-build HUB=higress TAG=v2.2.4`（产物 `higress/higress:v2.2.4`；gateway 的 `proxyv2` 按 D1 方案 A 拉发行镜像 `higress/proxyv2:v2.2.4`）
- [ ] `minikube image load higress/higress:v2.2.4`（体积大，留足时间；proxyv2 也 load 或用 pullPolicy）
- [ ] 记录构建 log 到 `infra/minikube/logs/core-build.log`
- ✅ 检查点：`minikube image list | grep higress` 含 `higress/higress`；镜像 tag 正确

### Task 3 — 构建 Higress Console 镜像（Java+前端源码）
- [ ] `cd higress-console/frontend && npm install && npm run build`（如遇 SSL 报错加 `NODE_OPTIONS=--openssl-legacy-provider`）
- [ ] 把前端 build 产物并入后端（按 console 仓库说明，或 `backend/build.sh` 会处理）
- [ ] `cd backend && ./build.sh`（Maven Wrapper `./mvnw`；脚本内 docker 命令先注释掉，跑本地 jar 构建）
- 产出：`console/target/higress-console.jar`
- [ ] 写自定义最小 Dockerfile（`FROM eclipse-temurin:21-jdk` + `COPY console/target/higress-console.jar /app/` + `COPY start.sh /app/` + `WORKDIR /app` + `CMD [/app/start.sh]`），`docker build -t higress-console/console:v2.2.4 .`（**绕开官方 Dockerfile 的 mcp COPY 缺失**，见 D3-A）
- [ ] `minikube image load higress-console/console:v2.2.4`
- ✅ 检查点：java -jar 冒烟 `higress-console.jar --local` 能起；`minikube image list` 含 console

### Task 4 — Helm 部署（两个 chart，用本地镜像）
- [x] **chart A 主集群**：用 `higress/helm/core`（或 `helm repo add higress.io https://higress.cn/helm-charts`）：`helm show values` 先核对 `global.local`、`o11y.enabled`、`gateway`/`controller` `service.type=NodePort`+`nodePort`、`global.hub/tag`、`imagePullPolicy`
- [x] 写 `infra/minikube/higress-values.yaml`：local=true、o11y=false、NodePort 30080/30443/30001、`global.hub`/tag 指向本地镜像名 + `imagePullPolicy: IfNotPresent`（proxyv2 走 global.hub；若方案 A 拉发行则保持官方 hub）
- [x] 装 chart A：
  ```bash
  helm install higress -n higress-system --create-namespace \
    -f infra/minikube/higress-values.yaml <higress/helm/core 或 higress.io/higress>
  ```
- [x] 等 controller/gateway/内置 nacos 全 Running
- [ ] **chart B console**：用 `higress-console/helm`（独立 chart），`-f` 指向 console 本地镜像 tag；等 console Pod Running
- ✅ 检查点：`kubectl -n higress-system get pods` 全 Running；`helm list -n higress-system` 两个都 deployed

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
| proxyv2 源码编译重/失败 | 高 | 默认走方案 A（混合），controller+console 源码、proxyv2 拉发行 |
| console `tools/mcp` tag 缺失 | 高（已解） | 改用 `backend/build.sh` 出 jar + 自定义 Dockerfile，绕开官方 Dockerfile 的 mcp COPY；要 mcp 再从 main 分支补二进制 |
| Node24 老前端构建 | 中 | `--openssl-legacy-provider` |
| Go 工具链缺失 | 中 | Task 0 先装 |
| Helm chart 键名差异 | 中 | `helm show values` 先核对 |
| minikube 镜像拉取慢 | 中 | 国内 mirror + 本地 image load（核心零外拉） |
| 每次全量编译耗时 | 中 | controller 增量、console 仅 Java；可拆 Task 分开跑 |
| **本次破坏动作集** | - | 停容器（已做）、`minikube delete`（预留，先 `docker start higress` 保障）|

## 明确不做
- ❌ 不做 proxyv2 全源码（Envoy 编译）——除非用户明确要
- ❌ 不把 HiMarket 7 容器迁进 K8s
- ❌ 不启用 o11y（prometheus/grafana/skywalking），跑通后二期
- ❌ 不动 Tailscale Funnel / nginx / 宿主 443
- ❌ 不删旧容器与 `~/himarket-data` 卷

## 本环境专属踩坑（Task 1 实测，2026-09-17）

## 🐛 坑：minikube 启动失败 `mark-control-plane: nodes "minikube" not found` / `Unable to register node`

**症状**：kubelet 健康、apiserver/etcd/scheduler 全 Running，但 kubelet 报
`Unable to register node with API server: Post https://192.168.49.2:8443/api/v1/nodes: proxyconnect tcp: dial tcp 127.0.0.1:7890: connection refused`

**根因（三级定位，非时序竞争）**：
1. 本机 **docker daemon 的 systemd 单元**强加代理：
   ```
   systemctl cat docker →
     Environment=HTTP_PROXY=http://127.0.0.1:7890
     Environment=HTTPS_PROXY=http://127.0.0.1:7890
     Environment=NO_PROXY=127.0.0.0/8,172.16.0.0/12,10.0.0.0/8,localhost
   ```
2. minikube 用 docker 起节点容器时，docker 把**自己的** `HTTP(S)_PROXY`/`NO_PROXY` 强加进容器 env（优先级最高，覆盖 `--docker-env` 与 shell 的 unset）。
3. 该 `NO_PROXY` **缺 minikube 集群 IP 网段 `192.168.49.0/24`**，导致 kubelet 带
   `HTTPS_PROXY=http://127.0.0.1:7890` 去连内网 apiserver `192.168.49.2:8443`，走代理 → 连接被拒 → Node 注册失败 → mark-control-plane 找不到 node。

**解法（方案 A，用户已确认）**：给 docker 加 systemd drop-in，只在 NO_PROXY 里**追加**集群网段：
```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
echo '[Service]' | sudo tee /etc/systemd/system/docker.service.d/minikube-noproxy.conf
echo 'Environment=NO_PROXY=127.0.0.0/8,172.16.0.0/12,10.0.0.0/8,192.168.49.0/24,localhost' | sudo tee -a /etc/systemd/system/docker.service.d/minikube-noproxy.conf
sudo systemctl daemon-reload
sudo systemctl restart docker   # ⚠️ 重启所有在跑容器(except 2 wso2: restart=no)
```
重启后 minikube 需 `minikube delete -p minikube` + 重 `start`。

**另一种思路（备选）**：不修 docker，改用 `minikube tunnel` / `kubectl port-forward` 暴露端口。会牺牲 `--ports` 的持久性。

**通用教训**：本机 docker daemon 全局代理（systemd `Environment=`)会被注入到**每个**用 docker 起的容器。凡容器内组件需访问集群内部地址（kubelet→apiserver、容器→网关），token NO_PROXY 必须含这些内网网段，否则走代理必失败。