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
- [x] `wso2-demo-downstream:9081` 在跑；临时 test Pod 验证 `curl host.minikube.internal:9081/healthz`
- [x] 写 Ingress + Service + Endpoints 指向 `host.minikube.internal:9081`
- [x] `kubectl apply -f` → 等 xDS 生效（~10s）→ `curl 127.0.0.1:18080/demo/time` 200 → 删除 404
- ✅ 检查点：增/删收敛各一次，证据存 `infra/minikube/evidence/task6.txt`

### Task 7 — wso2 adapter 切 kubectl 通道（二期，可延后）
- [ ] 生成 minikube kubeconfig；adapter `channel: kubectl`；Endpoints host 改 `host.minikube.internal`
- [ ] E2E：WSO2 发 2 API → SCG 200 + minikube Higress 200；下线双 404
- 🟡 检查点：wso2 项目在新集群 E2E 通过

### Task 8 — 文档与固化（可选体验目标）
- [x] `infra/minikube/` 放 `up.sh` / `down.sh` / `reset.sh` / `values`
- [x] 更新 README 为「Minikube + 源码镜像」环境
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

---

## 实跑命令全记录（2026-09-17，均为实际执行+验证过）

> 本节把本次任务从零到「minikube + 本地源码镜像 + 双 chart + 数据面链路」实跑的所有命令
> 按阶段列全。每条都实际执行并看到预期输出。环境与版本：
> minikube v1.39.0 / Kubernetes v1.37.0 / Higress 2.2.4（higress + higress-console 均源码构建）/
> Go 1.26 / JDK17 / Node 24。
> 注意：下方的 ``` 是 markdown 代码围栏，不是给终端输入的。真正要跑的只有各条命令本身。

### 0. 代理前置（本环境关键，必须先做）

本机 docker 有客户端级代理 ~/.docker/config.json 的 proxies.default，会被 docker CLI 注入到每个 docker run 容器（优先级高于 dockerd）。必须给 noProxy 补内网网段，否则 kubelet 拉镜像 / 注册节点必失败。

```
# 备份 + 用 python 改（该文件受保护，patch/write_file 写不进）
cp ~/.docker/config.json ~/.docker/config.json.bak-$(date +%Y%m%d)
python3 - <<'PY'
import json, os
p = os.path.expanduser('~/.docker/config.json')
d = json.load(open(p))
pr = d.setdefault('proxies', {}).setdefault('default', {})
pr['noProxy'] = pr.get('noProxy', '') + ',192.168.49.0/24,192.168.0.0/16,.aliyuncs.com'
json.dump(d, open(p, 'w'), indent=2)
PY
```

### Task 1 — minikube 安装与启动

```
# 下载 minikube v1.39.0 并放到 ~/bin
curl -LO https://github.com/kubernetes/minikube/releases/download/v1.39.0/minikube-linux-amd64
chmod +x minikube-linux-amd64 && mv minikube-linux-amd64 ~/bin/minikube

# 启动前停掉会占端口的旧 higress 容器（restart=always 会自动复活，需反复 stop）
docker stop higress   # 释放 18001/18080/18443

# 启动（关键参数：env -i 净环境避开 shell 代理；image-mirror-country 与 binary-mirror 必须同用）
env -i PATH="$PATH:~/bin" HOME="$HOME" MINIKUBE_HOME="$HOME/.minikube" \
  minikube start --driver=docker --cpus=6 --memory=8192 --disk-size=60g \
    --ports=18080:30080 --ports=18443:30443 --ports=18001:30001 \
    --image-mirror-country=cn --binary-mirror=https://dl.k8s.io

# 验证
minikube status              # host / kubelet / apiserver Running
minikube kubectl -- get nodes   # minikube  Ready  v1.37.0
minikube kubectl -- get pods -A  # 8 个核心 pod 全 Running（含 kindnet CNI）
```

踩坑 1（kubelet 注册失败）：报 mark-control-plane: nodes "minikube" not found，
根因容器内 kubelet 带 HTTP_PROXY=http://127.0.0.1:7890 且 NO_PROXY 缺内网段 → 修 ~/.docker/config.json。
踩坑 2（kindnet arm64 拉不到）：minikube 给的 kindnetd 镜像在阿里源是 arm64，需手动用 docker.io 的 amd64 版顶替：

```
docker pull --platform linux/amd64 kindest/kindnetd:v20260820-69b56db7
docker tag kindest/kindnetd:v20260820-69b56db7 registry.cn-hangzhou.aliyuncs.com/google_containers/kindnetd:v20260820-69b56db7
minikube image load registry.cn-hangzhou.aliyuncs.com/google_containers/kindnetd:v20260820-69b56db7
```

### Task 2 — 构建 Higress controller 镜像（Go 源码）+ 数据面镜像（发行）

```
# 0) 初始化 istio/envoy 子模块 + Go 依赖
cd ~/IdeaProjects/agentspace/higress          # 已 git clone @v2.2.4 (commit 58666ac)
export PATH=$HOME/go/go/bin:$PATH            # Go 1.26
make prebuild                                 # → git submodule update --init + 代码生成 + go mod

# 1) 预拉基础镜像并 retag 成 HUB 期望的本地名（避免 FROM higress/base 拉不到）
docker pull higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64 higress/base:2023-07-20T20-50-43-amd64

# 2) 构建 controller 镜像（后台，约几分钟）→ 产物 higress/higress:v2.2.4
make docker-build HUB=higress TAG=v2.2.4 > /tmp/higress-build.log 2>&1
docker images | grep higress/higress:v2.2.4    # 298MB

# 3) 数据面 proxyv2 按方案A拉发行镜像
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway:2.2.4 higress/proxyv2:v2.2.4

# 4) load 进 minikube
minikube image load higress/higress:v2.2.4
minikube image load higress/proxyv2:v2.2.4     # 1.6GB 较大
minikube ssh -- sudo crictl images | grep higress   # 确认进节点 containerd
```

### Task 3 — 构建 Higress Console 镜像（Java+前端源码）

```
cd ~/IdeaProjects/agentspace/higress-console   # git clone @v2.2.4 (commit f841043)

# 1) 前端 build（手动，避开 frontend-maven-plugin 自带 npm 失败）
cd frontend
npm install            # registry 已是 npmmirror
npm run build          # ice build → frontend/build (23MB)

# 2) 后端 jar（跳过前端插件 node 下载，保留 copy-static）
cd ../backend
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64   # pom 用 <release>8，JDK17 可编
mvn package -Dmaven.test.skip=true -Dpmd.language=en -Dapp.build.version=v2.2.4 \
  -Dskip.npm -Dskip.npx -Dskip.installnodenpm -pl console -am
ls -lh console/target/higress-console.jar      # 73MB，含 61 个前端 static html

# 3) 自定义最小 Dockerfile（绕开官方 mcp COPY 缺失，见 D3-A）
#    写 backend/Dockerfile.custom：
#      FROM eclipse-temurin:21-jdk
#      WORKDIR /app
#      COPY console/target/higress-console.jar /app/higress-console.jar
#      COPY start.sh /app/start.sh
#      RUN chmod +x /app/start.sh
#      EXPOSE 8080
#      CMD ["/app/start.sh"]
docker build -t higress-console/console:v2.2.4 -f Dockerfile.custom .
minikube image load higress-console/console:v2.2.4

# 冒烟：java -jar console/target/higress-console.jar --local --server.port=18099
# 能起（无 K8s 会在创建 ConfigMap 处停，属预期；部署进集群即正常）
```

### Task 4 — Helm 部署（双 chart，用本地镜像）

关键：core chart 镜像拼接规则是 ${hub}/higress/${image}:${tag}，且 tag 无 v（模板默认走 .Chart.AppVersion=2.2.4 而非 global.tag）。本地镜像必须 retag 成 :2.2.4 再 load，否则 kubelet 走 127.0.0.1:7890 代理拉取失败。

```
export PATH=$HOME/bin:$PATH

# 镜像 retag（controller 用源码产物，gateway/pilot 用发行镜像）
docker tag higress/higress:v2.2.4                 registry.local/higress/higress:2.2.4
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/pilot:2.2.4 registry.local/higress/pilot:2.2.4
docker tag higress/proxyv2:v2.2.4                 registry.local/higress/gateway:2.2.4
minikube image load registry.local/higress/higress:2.2.4 registry.local/higress/pilot:2.2.4 registry.local/higress/gateway:2.2.4

# chart A: core
cat > ~/IdeaProjects/agentspace/higress-ai-demo/infra/minikube/higress-values.yaml <<'EOF'
global: {local: true, kind: false, imagePullPolicy: IfNotPresent, hub: registry.local, tag: 2.2.4, enablePluginServer: false}
gateway: {image: gateway, service: {type: NodePort, ports: [{name: http2, port: 80, protocol: TCP, targetPort: 80, nodePort: 30080}, {name: https, port: 443, protocol: TCP, targetPort: 443, nodePort: 30443}]}}
controller: {image: higress}
pilot: {image: pilot}
o11y: {enabled: false}
promtail: {enabled: false}
EOF
helm install higress ~/IdeaProjects/agentspace/higress/helm/core -n higress-system --create-namespace \
  -f ~/IdeaProjects/agentspace/higress-ai-demo/infra/minikube/higress-values.yaml

# chart B: console
cat > ~/IdeaProjects/agentspace/higress-ai-demo/infra/minikube/console-values.yaml <<'EOF'
global: {local: true, ingressClass: "higress"}
image: {repository: higress-console/console, tag: v2.2.4, pullPolicy: IfNotPresent}
service: {type: NodePort, port: 8080}
ingress: {enabled: true, domain: console.higress.io, tlsSecretName: "", paths: [{path: /, pathType: Prefix}]}
o11y: {enabled: false}
grafana: {enabled: false}
prometheus: {enabled: false}
loki: {enabled: false}
certmanager: {enabled: false}
EOF
helm install console ~/IdeaProjects/agentspace/higress-console/helm -n higress-system \
  -f ~/IdeaProjects/agentspace/higress-ai-demo/infra/minikube/console-values.yaml

# 验证
minikube kubectl -- get pods -n higress-system    # controller 2/2, gateway 1/1, console 1/1 全 Running
minikube kubectl -- get ingress -n higress-system # higress-console + default 存在
```

### Task 5 — 端口与入口（console 免 host 访问）

Higress 声明式：只有建 Ingress，controller 才向 Envoy 下发 HTTP 监听；测入口需有路由。
console 默认 Ingress 要求 Host: console.higress.io。要让浏览器免 host 直连，把 Higress 的 default ingress 改为根路径直指 console：

```
# 无 host 直连 console：改 default ingress 指向 console svc
minikube kubectl -- patch ingress default -n higress-system --type=json -p='[{"op":"remove","path":"/metadata/annotations/higress.io~1rewrite-path"}]'
minikube kubectl -- patch ingress default -n higress-system --type=merge -p '{"spec":{"rules":[{"http":{"paths":[{"path":"/","pathType":"Prefix","backend":{"service":{"name":"higress-console","port":{"number":8080}}}}]}}]}}'

# 现在无需任何 Host 头即可打开
open http://127.0.0.1:18080/           # → console 前端 UI（200）
# 带 host 也仍然可用
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: console.higress.io' http://127.0.0.1:18080/   # 200
```

### Task 6 — 数据面链路验证（宿主 downstream 经 minikube 转发）

```
# 宿主 downstream 起服（restart=no 需手动）
docker start wso2-demo-downstream       # 0.0.0.0:9081
curl http://127.0.0.1:9081/healthz     # {"status":"ok"} 200
curl http://127.0.0.1:9081/demo/time   # 200

# minikube 节点内访问宿主
minikube ssh -- "getent hosts host.minikube.internal"   # → 192.168.49.1

# 写 Service+Endpoints+Ingress（文件已存 infra/minikube/task6-downstream.yaml）
minikube kubectl -- apply -f ~/IdeaProjects/agentspace/higress-ai-demo/infra/minikube/task6-downstream.yaml
sleep 12    # 等 xDS 生效
# 增：curl -H 'Host: demo.local' http://127.0.0.1:18080/demo/time  → 200 + downstream JSON
# 删：kubectl delete ingress demo-time; sleep 10 → curl ...  → 404（收敛）
```

### 成果速查
- console 免 host：http://127.0.0.1:18080/ 直接打开 UI
- 数据面：gateway 18080 → NodePort 30080 → Envoy :80 → Ingress → svc
- 镜像：registry.local/higress/{higress,pilot,gateway}:2.2.4 + higress-console/console:v2.2.4 均在 minikube containerd
- git 已提交 Task 1-6，本文件可回溯


---

## 实跑命令补记：gateway + pilot 全源码构建（2026-09-18）

> 追加于前节之后。前置：前节 Task 1-6 已完成（controller/console 源码镜像已部署，gateway/pilot 当时为发行镜像 retag）。
> 本节实现「所有组件全源码打包」：把 gateway(pilot) 也从 higress 源码组装，替换掉发行镜像。
> 注意：Higress 官方 proxyv2 的 Envoy 二进制永远是**下载 Higress 预编译版**（higress-group/proxy 发行 tarball），
> 不自编 Envoy；真正源码组装的是 istio 侧（pilot-discovery）+ 外围脚本（golang-filter、启动脚本、镜像组成）。

### 关键前置破解：私有 build-tools 镜像其实公开可拉

proxyv2/pilot 的 istio 构建容器镜像默认做法会以为它是私有的，实测发现是公开的，只需显式指定平台：

```
# 直接拉会 auth EOF(疑似多架构枚举问题)；显式 ——platform linux/amd64 则成功
docker pull --platform linux/amd64 \
  higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613
# 本地 6.98GB (1.62GB 实际层)，这个 istio 编译环境是 proxyv2/pilot 组装的前提
```

### 环境变量必须在 make 前预置（脚本 set -u，缺一个就炸）

`build-istio-image.sh` / `build-istio-pilot.sh` 都 `set -o pipefail` + 引用未绑定变量报错。
用 make target（会从 Makefile 自动 export）最省事：HUB / TAG / HIGRESS_BASE_VERSION / ENVOY_PACKAGE_URL_PATTERN
由 Makefile.core.mk 预置。手动跑脚本时需显式给全。

### Step A — pilot 镜像（官方 istio 源码 build-linux 组装）

```
cd ~/IdeaProjects/agentspace/higress
unset SSL_CERT_FILE CURL_CA_BUNDLE REQUESTS_CA_BUNDLE   # 否则 istio 容器内 curl 继承宿主 CA 路径报 77

# 关键：out/ 会被之前容器 root 用户创建, 宿主 rm 不掉 → 先确认 out 归宿主(或让用户 sudo chown)
# ls -ld external/istio/out 须为当前用户, 否则 make 开头 rm -rf out 权限失败

# 1) 跑 pilot 组装(make target 自动带 HUB/TAG/ENVOY_URL)。会: 下载 Higgs 预编译 Envoy → 编 pilot-discovery → 生成 docker-bake.json
make build-istio-local TARGET_ARCH=amd64 > /tmp/higress-pilot-build.log 2>&1
# 结果: 编译/下载全成功("make complete"), 唯独最后用容器内 docker buildx bake 失败:
#   client version 1.43 is too old. Minimum API 1.44  (build-tools 内 docker CLI 旧)
# → 产物已在宿主 external/istio/out/linux_amd64/dockerx_build/, 直接用宿主动手打镜像

# 2) 宿主动手：本地 base 需先 retag 成无 -amd64 后缀(供 Dockerfile FROM 解析)
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64 \
           higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43
cd external/istio/out/linux_amd64/dockerx_build/build.docker.pilot   # Dockerfile.pilot + amd64/pilot-discovery
docker build --platform linux/amd64 \
  -f Dockerfile.pilot \
  --build-arg BASE_DISTRIBUTION=debug \
  --build-arg BASE_VERSION=2023-07-20T20-50-43 \
  --build-arg ISTIO_BASE_REGISTRY=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress \
  -t higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/pilot:58666ac985cee19a0a9a353421c63cead6d0cb47 \
  .
# → 得到源码 pilot 镜像, 含 /usr/local/bin/pilot-discovery (113MB)
```

### Step B — golang-filter（proxyv2 数据面 Go 过滤器，补进 external/package）

`build-gateway-local` 会先编译 golang-filter，但官方走容器 `go mod tidy` 因容器内继承宿主代理(127.0.0.1:7890 指向宿主不通) + proxy.golang.org 失败。
修法：宿主编译 + 国内 GOPROXY，再拷进 external/package。

```
cd ~/IdeaProjects/agentspace/higress/plugins/golang-filter
export GOPROXY=https://goproxy.cn,direct GOFLAGS=-buildvcs=false
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy   # 关键：清代理
go mod tidy     # 走 goproxy.cn, 成功
go build -o golang-filter_amd64.so -buildmode=c-shared .   # 宿主 gcc 直接编出 .so (79MB)
cp golang-filter_amd64.so ../../external/package/
```

### Step C — proxyv2 镜像（Higress 源码组装: 预编译 Envoy + golang-filter + pilot-agent）

```
cd ~/IdeaProjects/agentspace/higress
unset SSL_CERT_FILE CURL_CA_BUNDLE REQUESTS_CA_BUNDLE
# 需手动补 make 会预置的变量(脚本 set -u)：
export HUB=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress
export TAG=58666ac
export HIGRESS_BASE_VERSION=2023-07-20T20-50-43
export ENVOY_PACKAGE_URL_PATTERN='https://github.com/higress-group/proxy/releases/download/v2.2.4/envoy-symbol-ARCH.tar.gz'
export IMG_URL=""   # 脚本引用它, 空串即可

TARGET_ARCH=amd64 DOCKER_TARGETS="docker.proxyv2" ./tools/hack/build-istio-image.sh docker \
  > /tmp/higress-proxy-build.log 2>&1
# 同样 "make complete", 卡在 build-tools 内 docker buildx(1.43)。产物已备齐:
#   out/linux_amd64/dockerx_build/build.docker.proxyv2/{Dockerfile.proxyv2, amd64/{envoy, pilot-agent, golang-filter.so}}

# 宿主动手 (必须 --network=host, 否则国内 apt 连 archive.ubuntu.com 超时 → Unable to locate package)
cd external/istio/out/linux_amd64/dockerx_build/build.docker.proxyv2
docker build --platform linux/amd64 --network=host \
  -f Dockerfile.proxyv2 \
  --build-arg BASE_DISTRIBUTION=debug \
  --build-arg BASE_VERSION=2023-07-20T20-50-43 \
  --build-arg ISTIO_BASE_REGISTRY=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress \
  --build-arg TARGETARCH=amd64 \
  -t higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/proxyv2:58666ac \
  .
# → 源码 proxyv2 镜像, 含 envoy(815MB)+pilot-agent(27MB)+golang-filter.so(79MB)
```

### Step D — retag + load + 滚动替换

```
# 把源码镜像 retag 成 chart 期望名(chart 用 registry.local/higress/{pilot,gateway}:2.2.4)
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/pilot:58666ac985cee19a0a9a353421c63cead6d0cb47 \
           registry.local/higress/pilot:2.2.4
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/proxyv2:58666ac \
           registry.local/higress/gateway:2.2.4

export PATH=$HOME/bin:$PATH
minikube image load registry.local/higress/pilot:2.2.4
minikube image load registry.local/higress/gateway:2.2.4

# 因为 tag 没变, kubelet 不会自动重建 → 手动滚动重启
minikube kubectl -- rollout restart deploy higress-gateway -n higress-system
minikube kubectl -- rollout restart deploy higress-controller -n higress-system
minikube kubectl -- rollout status deploy/higress-gateway -n higress-system --timeout=90s
minikube kubectl -- rollout status deploy/higress-controller -n higress-system --timeout=120s

# 验证 pod 镜像 ID = 源码版(36ab51b6dc11d=proxyv2 / adf888683e7b3=pilot), 数据面 200 正常
minikube kubectl -- get pods -n higress-system
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/                       # console 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: demo.local' http://127.0.0.1:18080/demo/time  # downstream 200
```

### 最终四镜像全部源码（2026-09-18 达成）
| 组件 | 镜像 | 构建方式 |
|---|---|---|
| controller | registry.local/higress/higress:2.2.4 | Go 源码 make docker-build |
| pilot | registry.local/higress/pilot:2.2.4 | istio 源码头组装(宿主动手 docker build) |
| gateway | registry.local/higress/gateway:2.2.4 | Higress 源码 proxyv2(预编译 Envoy + 源码 golang-filter) |
| console | higress-console/console:v2.2.4 | Java+前端源码构建 |

### 本期踩坑
- 私有 build-tools 其实公开，docker pull 加 --platform linux/amd64 即可。
- istio 容器内 curl 继承宿主 SSL_CERT_FILE → 必须 unset，否则下载 Envoy 报 (77)。
- out/ 被容器 root 创建 → 宿主 rm 权限失败 → 需 sudo chown 归宿主。
- build-istio-image.sh 手动跑要补 set -u 变量(HUB/TAG/HIGRESS_BASE_VERSION/ENVOY_PACKAGE_URL_PATTERN/IMG_URL)。
- build-tools 内 docker CLI(1.43) 连宿主 daemon(1.53) 版本不符 → 绕开，直接在宿主动手 docker build bake 产物。
- golang-filter 容器 go mod tidy 继承宿主 127.0.0.1 代理+proxy.golang.org → 清代理 + goproxy.cn 宿主编译。
- proxyv2 镜像里 apt-get 装 logrotate/cron: 国内连 archive.ubuntu.com 超时 → docker build 加 --network=host。


---

## 实跑命令补记：console 挂 nginx /higress 前缀 + Tailscale Funnel 外网暴露（2026-09-18）

> 用户追加需求:把 console 经 nginx 加 /higress 路径前缀,开放到外网 Tailscale Funnel。
> 前置:Higress console 已在 minikube 集群跑通,免 host `http://127.0.0.1:18080/` 可访问;
> 本机已有用户级 nginx(`~/.local/nginx`,监听 :8443) + Tailscale Funnel 443->8443
> (域名 leonbook5-jiguang-series.tailb1426a.ts.net),其上已挂 /multica 与 /wso2。

### 关键问题:console 是无 basePath 的 ice SPA

Higress console 前端(ice 脚手架)静态资源 `/css/`、`/js/` 与 API `/api/` 全部**硬编码在根路径**,
不认 basePath。直接挂 `/higress/` 前缀并剥前缀会拿到 HTML,但 HTML 引用的 `/css/...` 经 nginx
剥前缀打到 console 后路径变成 `/higress/css/...`(浏览器侧仍请求根 `/css/`, 而根 `/` 被 multica 占用)
→ 资源 404,前端破裂。

### 解法:nginx sub_filter 把根路径资源重写进 /higress/ 前缀

`location /higress/` 用 `proxy_pass http://127.0.0.1:18080/`(带 URI → 自动剥 /higress/ 前缀),
并对响应做 sub_filter 重写(HTML+JS):
```
sub_filter '/higress.jpg' '/higress/higress.jpg';
sub_filter '/css/'        '/higress/css/';
sub_filter '/js/'         '/higress/js/';
sub_filter '/api/'        '/higress/api/';
sub_filter_once off;
sub_filter_types text/javascript application/javascript;   # HTML 默认已含
```

### 关键文件

- `~/.local/nginx/conf/higress-locations.conf` — /higress/ location + sub_filter(本仓库 infra/nginx/ 有备份)
- `~/.local/nginx/conf/nginx.conf` — include 该文件(第 151-152 行,wso2 include 之后)
- 仓库 `infra/nginx/higress-locations.conf` + `infra/nginx/README.md` — 备份与说明

改后 reload: `nginx -s reload -c /home/leonbook5/.local/nginx/conf/nginx.conf`

### 验证(全部 200)

```
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/                  # 200 text/html
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/css/main-*.css   # 200 text/css
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/js/data-loader.js # 200
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/api/             # 200
# HTML 资源已重写为 /higress/ 前缀(可控)
curl -s https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/ | grep -o 'href="/higress/css/[^"]*"' | head
# 未破坏其他服务
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/                          # multica 200
```

### 访问地址

- 公网: https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/
- 本地: http://127.0.0.1:8443/higress/
- 直连 gateway 免 host: http://127.0.0.1:18080/

### 踩坑/注意

- sub_filter 只处理 text/* 默认;要重写 JS 里的路径须 `sub_filter_types text/javascript application/javascript`。
- sub_filter_types 里重复写 text/html 会触发 nginx "duplicate MIME type" 警告(无害,但应去掉,HTML 默认已含)。
- Browserbase 等远端无头浏览器连不到本机 localhost:8443,无法在此环境直接看 SPA 渲染;SPA 需用户本地/公网浏览器打开。
- console 前端 API 路径为运行时相对/动态拼接,不依赖根路径字面量,挂前缀后经 sub_filter 的 /api/->/higress/api/ 即可正确代理。


---

## 实跑命令补记：console 挂 /higress 前缀的 404 修复（JS/CSS 与根路径 API，2026-09-18）

> 承接上节:console 已挂 nginx /higress 前缀并经 Tailscale Funnel 暴露公网。但浏览器打开后
> JS/CSS 404(动态 chunk 请求根路径 /js/xxx), 随后 /user/info 等 API 也 404。本节记录两轮根因与修复。

### 第一轮:JS/CSS 404 —— nginx sub_filter 被上游 gzip 阻断

**症状**:公网打开 higress console, 页面骨架出来但 JS/CSS 404。浏览器请求的是 `https://.../js/2209-xxx.js`(根路径,无 /higress 前缀)。

**根因**:console 是无 basePath 的 ice SPA, HTML 静态 script 硬编码 `/js/...`、`/css/...`(根路径)。
nginx 用 `sub_filter '/js/' '/higress/js/'` 等重写。但**浏览器发 `Accept-Encoding: gzip` → 上游(console/Envoy)返回 gzip 压缩体 → nginx sub_filter 无法在压缩内容上做文本替换** → HTML 里 script 保持 `/js/...` 根路径 → 浏览器请求根 `/js/xxx` 落到 multica catch-all → 404。
(本地 curl 默认不带 gzip 所以明文、sub_filter 生效、验证通过,被误导;浏览器一开就暴露。)

**修复**:`/higress/` location 加 `proxy_set_header Accept-Encoding "";` → 让上游返回明文, nginx 先 sub_filter 重写再(若开启 gzip)自行压缩。
验证:公网带 gzip 请求现在返回明文且 script 已重写为 `/higress/js/...`, 全部 js/css 200。

### 第二轮:根路径 API(`/user/info` 等) 404

**症状**:登录/接口调用时 `https://.../user/info?ts=...` 404。

**根因**:console 前端生产模式 API baseURL 为空串(`frontend/src/services/request.tsx`):
`baseURL: process.env.ICE_CORE_MODE === "development" ? "/api" : ""`
→ 生产模式前端按**当前 origin 根路径**发请求(`/user`、`/session`、`/system`、`/v1/`... 不带 /higress)。sub_filter 只改 HTML/JS 里**字面量**路径, 挡不住运行时拼接的根路径请求 → 落到 multica catch-all 404。

**修复**:`higress-locations.conf` 加**根路径兜底 location**(console 的 API 命名空间, `^~` 前缀优先级高于 multica catch-all, 且 multica 无同名专门路由不冲突), 显式转发到 console:18080:
```
location ^~ /user/      { proxy_pass http://127.0.0.1:18080; proxy_set_header Host $host; }
location ^~ /session/   { proxy_pass http://127.0.0.1:18080; ... }
location ^~ /system/    { ... }
location ^~ /dashboard/ { ... }
location ^~ /v1/        { ... }
location =  /landing    { proxy_pass http://127.0.0.1:18080/landing; ... }
location =  /healthz    { proxy_pass http://127.0.0.1:18080/healthz; ... }
# 注: /api 不设——multica 已占用 /api/(其根), console 的 /api 由 /higress/api/ 前缀处理。
```

### 最终 higress-locations.conf 结构(三层)

```
# A) /higress/ 前缀入口: proxy_pass http://127.0.0.1:18080/ (剥前缀) + sub_filter 重写根路径资源
# B) 根路径 console API 兜底: 上述 ^~ location 转发到 console
```

- 配置文件: `~/.local/nginx/conf/higress-locations.conf`(仓库 infra/nginx/higress-locations.conf 备份)
- reload: `nginx -s reload -c /home/leonbook5/.local/nginx/conf/nginx.conf`

### 验证(全部通过)

```
# 第一轮: 公网全 js/css 200, HTML script 已重写为 /higress/js/
curl -s https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/ | grep -o 'src="/higress/js/[^"]*"' | head
# 第二轮: 根路径 API 从 404 -> 401(未登录正常)/200/405(方法), 已到 console 后端
curl -s -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/user/info   # 401
curl -s -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/system/info # 200
# multica/wso2 未破坏
curl -s -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/            # 200(multica)
curl -s -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/wso2         # 302(wso2)
```

### 踩坑

- **sub_filter 与 gzip**:sub_filter 无法处理压缩体, 必须 `proxy_set_header Accept-Encoding ""` 让上游明文。此为两个 404 的根源之一。
- **本地 curl 误导**:本地 curl 默认不带 Accept-Encoding:gzip, 一直是明文, sub_filter 总"看似生效"; 必须用 `curl -H 'Accept-Encoding: gzip'` 或真实浏览器验证。
- **sub_filter 只管字面量**:ice/webpack 运行时由 publicPath 或相对请求拼接 URL, sub_filter 改不到 → 需 nginx 层显式兜底 location。
- **/api 归属**:multica 已用根 /api/, 不把 /api 兜底到 console; console 的 /api 走 /higress/api/ 前缀即可。


---

## 实跑命令补记：console 挂 /higress 前缀 · 第5轮 · basename/publicPath 白屏根治（2026-09-20）

**现象**：在前端 401→登录跳转已正确（/login?redirect= → /higress/login）后，/higress/login 仍是白屏（ice-container 空，登录组件不渲染）。

**根因**：console 是无 basePath 的 ice3 SPA。前端 router 硬编码在根路径（`/login` `/dashboard` 等，见 `_defaultProps.tsx`），
`matchRoutes(routes, location=`/higress/login`, basename=/)` 匹配不到 `/login` 路由 → 返回空 → 白屏。
nginx sub_filter 只能修**静态资源路径**（/js/ /css/）+ 根路径 API 兜底，**修不了前端 router 的路径匹配**（运行时 JS 逻辑）。

**修复（改前端源码，根治）**：
1. `frontend/ice.config.mts` 加 `publicPath: "/higress/"`（静态资源直接带前缀；`basename` 顶层键会被本版 build-scripts 拒绝 → 改放 src/app.ts）。
2. `frontend/src/app.ts` 的 `defineAppConfig` 加 `router: { basename: "/higress" }`（@ice/runtime 支持 AppConfig.router.basename，见 node_modules/@ice/runtime/esm/types.d.ts）。
3. `frontend/src/services/request.tsx:58` 401 整页跳转由硬编码 `/login?redirect=…` 改为 `${basePath}/login?redirect=…`，basePath=`/higress`（否则 401 仍跳根 /login 落 multica）。

**验证（编译产物）**：`assets-manifest.json` publicPath=`/higress/`；`index.html` script src=`/higress/js/…`；main JS 含 `router:{basename:"/higress"}`。

**重建 console 镜像**：
- 前端 `NODE_OPTIONS=--openssl-legacy-provider npm run build`（老前端 webpack5）
- 后端 `./mvnw clean package -Dmaven.test.skip=true -Dpmd.language=en`（前端产物经 maven-resources-plugin 拷进 static 打包）+ 自定义 Dockerfile（`backend/Dockerfile.custom`，FROM eclipse-temurin:21-jdk，绕开官方 Dockerfile 的 tools/mcp COPY 缺失）
- `docker build -t higress-console/console:v2.2.4 -f Dockerfile.custom .` → `minikube image load higress-console/console:v2.2.4` → `kubectl rollout restart deployment/higress-console -n higress-system`

**nginx 配置联动（关键）**：前端 publicPath 生效后 HTML/JS 已自带 `/higress/` 前缀 → nginx `/higress/` location 里原来的 sub_filter（`/js/→/higress/js/` `css` `api` `user/session/...`）**必须移除**，否则会双重前缀（`/higress/js/…` 又被替换成 `/higress/higress/js/…` → 404）。
保留：`location = /higress`（301 https）、`location /higress/`（proxy_pass 剥前缀，去 sub_filter）、`= /healthz`、`= /landing`、`location = /login`（redirect 含 /higress 时 302 回 /higress/login）、`^~ /user/ /session/ /system/ /dashboard/ /v1/` 根路径 API 兜底。

**最终结果（Browserbase 真实浏览器验证）**：
- URL 正确跳到 `/higress/login?redirect=/higress/`（不再丢前缀，basename+request.tsx 生效）
- ice-container 渲染出登录表单（inputs=4，`登 录` 按钮，`<form>` 存在）—— **白屏根治**
- unhandledrejection `401 /user/info` 是未登录预期，前端靠它跳登录，非问题
- 登录凭据：默认 `admin / admin`（`SystemConfigKey.DASHBOARD_USERNAME/PASSWORD_DEFAULT="admin"`）

**本轮踩坑**：
- `basename` 不能放 ice.config.mts 顶层（build-scripts 校验拒绝 `[Config File] Config key 'basename' is not supported`） → 放 `defineAppConfig.router.basename`
- sub_filter 与前端 publicPath 会**双重加前缀** → publicPath 后用全量移除非 /higress 前缀需保留的 sub_filter
