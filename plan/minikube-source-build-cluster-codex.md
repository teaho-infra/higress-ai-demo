# Higress 源码镜像、Minikube 与 xDS/Wasm 实跑记录（Codex）

> 本文记录 2026-09-28 在 `teaho-ThinkPad-E14-Gen-2` 上**实际执行且验证成功**的命令。旧计划中的命令仅作参考，不自动视为本机已成功。命令以本机用户 `teaho` 执行，除非明确注明。

## 目标与验收

- 固定 Higress 和 Higress Console 源码版本 v2.2.4，构建 controller、pilot、gateway、console 镜像。Gateway 使用源码组装的数据面镜像；若 Envoy 二进制取官方预编译产物，会明确记录。
- 用 Docker driver 启动独立的 Minikube 单节点集群，Helm 部署 `higress-system` 中的 core 和 console。
- 用真实 Ingress 证明 controller → pilot → gateway 的 xDS 配置下发，以 Envoy `config_dump` 和 HTTP 响应双重验证。
- 安装一个 Wasm 插件，证明插件配置已下发，并以实际响应证明插件执行。

## 本机约束

- 当前主机 6 核、约 38 GiB 内存、无 swap。2026-09-28 开始时 `MemAvailable` 约 22 GiB。
- 原计划记录的是另一台 24 核机器，不能照搬资源结论。本次构建限制并发，Minikube 默认用 4 CPU、8 GiB。
- 原 `minikube` profile 配置残留但节点容器不存在；本次使用独立 profile，保留其他 profile。
- 原仓库 `up.sh` 写死默认 `minikube` profile；本次为避免改动其他 profile，使用等价的显式 `helm install --kube-context higress-dev` 命令。
- 使用宿主 18080/18443/18001 映射 NodePort 30080/30443/30001；如端口占用，以实际端口和命令为准。

## 执行状态

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 工具与源码 | 完成 | Higress `58666ac`，Console `f841043`，Go 1.26.0，Helm 3.16.4 |
| 镜像构建 | 完成 | Controller `107c54a9`、pilot `88abc55a`、gateway `2ceb4611`、Console `201e8e1b`；另有本地 Wasm 文件服务镜像 |
| Minikube 与 Helm 部署 | 完成 | `higress-dev` 节点 Ready；两套 Helm release 为 `deployed`；五个 Deployment 全部 Ready |
| xDS 与 gateway 验证 | 完成 | controller、pilot、Envoy 三段可见路由；ADS 客户端 1 个；路由更新后新域名 200、旧域名 404，恢复亦成功 |
| Wasm 插件验证 | 完成 | Gateway 取得 6,630,522 字节 Wasm；允许路径 200、屏蔽路径 403，日志 `via_wasm`；ECDS 更新成功、拒绝 0 |

## 成功命令逐条记录

以下仅追加**实际执行成功**的命令及关键结果。路径使用本机绝对路径，方便直接复制。

### 1. 工具与源码

1. 拉取固定版本源码（两条命令均退出码 0）：

   ```bash
   git clone --depth 1 --branch v2.2.4 https://github.com/higress-group/higress.git /home/teaho/IdeaProjects/agentspace/higress
   git clone --depth 1 --branch v2.2.4 https://github.com/higress-group/higress-console.git /home/teaho/IdeaProjects/agentspace/higress-console
   ```

   Higress commit `58666ac985cee19a0a9a353421c63cead6d0cb47`，Console commit `f8410432d450541baec3ae468e4d4a8a07392169`。

2. 安装 Helm 3.16.4（`helm version --short` 输出 `v3.16.4+g7877b45`）：

   ```bash
   curl -fsSL --max-time 25 https://get.helm.sh/helm-v3.16.4-linux-amd64.tar.gz -o /tmp/helm-v3.16.4-linux-amd64.tar.gz
   mkdir -p /home/teaho/.local/bin
   tar -xzf /tmp/helm-v3.16.4-linux-amd64.tar.gz -C /tmp linux-amd64/helm
   install -m 0755 /tmp/linux-amd64/helm /home/teaho/.local/bin/helm
   /home/teaho/.local/bin/helm version --short
   ```

3. 安装 Go 1.26.0（`go version` 输出 `go version go1.26.0 linux/amd64`）：

   ```bash
   curl -fL --retry 2 --connect-timeout 10 --max-time 180 https://go.dev/dl/go1.26.0.linux-amd64.tar.gz -o /tmp/go1.26.0.linux-amd64.tar.gz
   mkdir -p /home/teaho/tools/go1.26.0
   tar -xzf /tmp/go1.26.0.linux-amd64.tar.gz -C /home/teaho/tools/go1.26.0 --strip-components=1
   /home/teaho/tools/go1.26.0/bin/go version
   ```

4. 初始化 Higress 源码子模块，命令退出码 0（工作目录 `/home/teaho/IdeaProjects/agentspace/higress`）：

   ```bash
   git submodule update --init --depth 1
   ```

5. 安装 Console 前端依赖，2669 个 package 安装成功（工作目录 `/home/teaho/IdeaProjects/agentspace/higress-console/frontend`）：

   ```bash
   npm ci --allow-remote=all --no-audit --no-fund
   ```

   首次不带 `--allow-remote=all` 的尝试因 npm 12 默认 `allow-remote=none` 拒绝锁文件内的 `registry.npmmirror.com` tarball；本次只对该命令放行。安装期间 npm 提示多个依赖的安装脚本被默认安全设置拦截，前端构建结果仍需单独验证。

6. 主机重启留下的 Go 模块缓存有 1722 个 0 字节 `.mod`/`.zip` 文件，并且旧 `external/` 复制目录有 2406 个 0 字节 `.go` 文件。备份旧目录后用全新缓存重建。单独验证的 `google.golang.org/protobuf` 摘要与仓库 `go.sum`、官方 sumdb 一致。这里的关键是隔离受损缓存，**不修改 `go.sum` 或关闭校验**：

   ```bash
   mv /home/teaho/IdeaProjects/agentspace/higress/external /home/teaho/IdeaProjects/agentspace/higress/external-corrupt-2026-09-28
   mkdir -p /home/teaho/.cache/higress-go-mod
   ```

7. Higress 预构建完成（工作目录 `/home/teaho/IdeaProjects/agentspace/higress`，退出码 0）：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod \
     GOMAXPROCS=4 GOFLAGS=-p=4 make prebuild
   ```

   原来经本机 `127.0.0.1:7890` 代理的下载长时间停滞；直连镜像站并配置备用 Go 代理后成功。重新复制的 `external/`、新模块缓存中抽查的 `.go` 文件均非空。

8. 拉取源码构建容器及 Istio/Higress 基础镜像，再给 controller Dockerfile 所需的本地仓库名打标签：

   ```bash
   docker pull --platform linux/amd64 \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613
   docker pull --platform linux/amd64 \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64
   docker tag \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64 \
     higress/base:2023-07-20T20-50-43-amd64
   docker tag \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64 \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43
   ```

### 2. 镜像构建与载入

1. Console 前端构建成功（工作目录 `/home/teaho/IdeaProjects/agentspace/higress-console/frontend`，Webpack 5.75.0 输出 `compiled successfully`，341 个资源文件）：

   ```bash
   NODE_OPTIONS=--openssl-legacy-provider npm run build
   ```

2. Console 后端打包成功（工作目录 `/home/teaho/IdeaProjects/agentspace/higress-console/backend`，Maven Reactor 3 个模块全部 `SUCCESS`；`console/target/higress-console.jar` 为 73 MiB，含静态资源）：

   ```bash
   mvn package -Dmaven.test.skip=true -Dpmd.language=en -Dapp.build.version=v2.2.4 \
     -Dskip.npm -Dskip.npx -Dskip.installnodenpm -pl console -am
   ```

3. 从 Higress 源码编译参考 `request-block` Wasm 插件（工作目录 `/home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/examples/request-block`，`file` 确认为 WebAssembly 模块，大小 6.4 MiB）：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH GOPROXY=https://goproxy.cn,direct \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=2 GOOS=wasip1 GOARCH=wasm \
     go build -buildmode=c-shared -o main.wasm .
   file main.wasm
   ```

4. 使用仓库内 [Dockerfile.console-codex](../infra/minikube/Dockerfile.console-codex) 把源码构建的 JAR 打成 Console 镜像（工作目录 `/home/teaho/IdeaProjects/agentspace/higress-console/backend`，镜像摘要 `sha256:201e8e1b...`）：

   ```bash
   docker build -t higress-console/console:v2.2.4 \
     -f /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/Dockerfile.console-codex .
   ```

   v2.2.4 官方 Dockerfile 要求 `tools/mcp/${TARGETARCH}/main`，此 tag 不提供；最小 Dockerfile 打包已生成的 JAR 和原 `start.sh`，因此不含该可选 MCP 工具。

5. `make docker-build HUB=higress TAG=v2.2.4` 已把源码编译为 `out/linux_amd64/higress`，但该版本的 Docker 打包规则没有传 `TARGETARCH`，导致基础镜像标签末尾缺少 `amd64`。用其生成的构建上下文补齐参数，宿主镜像构建成功，摘要 `sha256:107c54a9...`（工作目录 `/home/teaho/IdeaProjects/agentspace/higress/out/linux_amd64/docker_build/docker.higress`）：

   ```bash
   docker build --platform linux/amd64 \
     --build-arg BASE_VERSION=2023-07-20T20-50-43 \
     --build-arg HUB=higress --build-arg TARGETARCH=amd64 \
     -t registry.local/higress/higress:2.2.4 -f Dockerfile.higress .
   ```

6. 为本地验证打包源码编译的 Wasm 模块，见 [Dockerfile.wasm-codex](../infra/minikube/Dockerfile.wasm-codex)。构建上下文为 `/home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/examples/request-block`，镜像摘要 `sha256:fe3eca9f...`：

   ```bash
   docker build -t registry.local/higress/codex-request-block:2.2.4 \
     -f /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/Dockerfile.wasm-codex .
   ```

7. Gateway 数据面所需的 Go filter 从源码编译为 76 MiB 的 Linux x86-64 共享库，并放入 Higress 构建包（工作目录 `/home/teaho/IdeaProjects/agentspace/higress/plugins/golang-filter`）：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=2 \
     GOFLAGS='-p=2 -buildvcs=false' \
     go build -o golang-filter_amd64.so -buildmode=c-shared .
   file golang-filter_amd64.so
   install -m 0644 golang-filter_amd64.so \
     /home/teaho/IdeaProjects/agentspace/higress/external/package/golang-filter_amd64.so
   ```

8. 构建容器直连 GitHub 下载 Envoy 长时间无数据；宿主网络代理可访问。将官方 v2.2.4 Envoy 压缩包下载到构建包目录并校验归档，SHA-256 为 `ce25343352de077106146c1a2a7c805ea7f246e134f0b92e9736f00453d48724`：

   ```bash
   curl -fL --retry 3 --connect-timeout 15 --max-time 300 \
     'https://github.com/higress-group/proxy/releases/download/v2.2.4/envoy-symbol-amd64.tar.gz' \
     -o /home/teaho/IdeaProjects/agentspace/higress/external/package/envoy-symbol-amd64.tar.gz
   tar -tzf /home/teaho/IdeaProjects/agentspace/higress/external/package/envoy-symbol-amd64.tar.gz | head -n 8
   sha256sum /home/teaho/IdeaProjects/agentspace/higress/external/package/envoy-symbol-amd64.tar.gz
   ```

   镜像将使用此**官方预编译 Envoy**，并结合源码编译的 pilot-agent 与 golang-filter 组装；这里不声称 Envoy 本身由本机源码编译。

9. Istio 构建容器以 root 写入 `external/istio/out`。再次构建前用本地已有镜像恢复目录所有权；以下命令成功（工作目录 `/home/teaho/IdeaProjects/agentspace/higress`）：

   ```bash
   docker run --rm \
     --mount type=bind,source=/home/teaho/IdeaProjects/agentspace/higress/external/istio/out,target=/work \
     --entrypoint chown registry.local/higress/codex-request-block:2.2.4 \
     -R 1000:1000 /work
   ```

10. 使用本地校验过的 Envoy 包完成源码 pilot 构建（工作目录 `/home/teaho/IdeaProjects/agentspace/higress`，退出码 0；最终镜像摘要 `sha256:88abc55a...`）：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     -u SSL_CERT_FILE -u CURL_CA_BUNDLE -u REQUESTS_CA_BUNDLE \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=4 GOFLAGS=-p=4 \
     make build-istio-local TARGET_ARCH=amd64 \
       ENVOY_PACKAGE_URL_PATTERN='file:///home/package/envoy-symbol-ARCH.tar.gz'
   docker tag \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/pilot:58666ac985cee19a0a9a353421c63cead6d0cb47 \
     registry.local/higress/pilot:2.2.4
   minikube -p higress-dev image load registry.local/higress/pilot:2.2.4
   ```

   Docker 构建日志结尾为 `images complete`、`build complete`；本机 Docker API 与构建容器兼容，pilot 无需手工重打镜像。

11. Gateway 打包前再次用第 9 步的 `docker run ... chown` 命令恢复 `external/istio/out` 所有权。然后从 Istio/Higress 源码构建 `pilot-agent` 并组装 proxyv2（工作目录 `/home/teaho/IdeaProjects/agentspace/higress`，退出码 0、日志结尾 `images complete` / `build complete`，摘要 `sha256:2ceb4611...`）：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     -u SSL_CERT_FILE -u CURL_CA_BUNDLE -u REQUESTS_CA_BUNDLE \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=4 GOFLAGS=-p=4 \
     HUB=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress \
     TAG=58666ac985cee19a0a9a353421c63cead6d0cb47 \
     HIGRESS_BASE_VERSION=2023-07-20T20-50-43 \
     ENVOY_PACKAGE_URL_PATTERN='file:///home/package/envoy-symbol-ARCH.tar.gz' \
     IMG_URL='' TARGET_ARCH=amd64 DOCKER_TARGETS=docker.proxyv2 \
     ./tools/hack/build-istio-image.sh docker
   docker tag \
     higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/proxyv2:58666ac985cee19a0a9a353421c63cead6d0cb47 \
     registry.local/higress/gateway:2.2.4
   minikube -p higress-dev image load registry.local/higress/gateway:2.2.4
   ```

   此镜像包含官方 Envoy 二进制、源码构建的 `pilot-agent`、源码构建的 `golang-filter_amd64.so`。本机 Docker 构建可直接完成，无需旧计划中的手动 bake 补救步骤。

### 3. Minikube 与 Helm

1. 新建独立 profile，限定 4 CPU、8 GiB 和 60 GiB 虚拟磁盘。命令退出码 0；节点 `Ready`，基础 Pod 全部 `Running`：

   ```bash
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     minikube start -p higress-dev --driver=docker --cpus=4 --memory=8192 --disk-size=60g \
       --kubernetes-version=v1.30.0 \
       --ports=18080:30080 --ports=18443:30443 --ports=18001:30001 \
       --image-repository=registry.cn-hangzhou.aliyuncs.com/google_containers
   minikube -p higress-dev status
   kubectl --context higress-dev get nodes -o wide
   kubectl --context higress-dev get pods -A
   ```

   本次节点 IP 为 `192.168.67.2`。原 `minikube` profile 未动。

   构建期间宿主机曾重启；恢复已有 profile 使用下列命令成功，Kubernetes 基础组件恢复为运行状态：

   ```bash
   minikube start -p higress-dev --driver=docker
   ```

2. 将已经构建的三个镜像及验证回显镜像载入 `higress-dev`，以下命令均退出码 0：

   ```bash
   minikube -p higress-dev image load higress-console/console:v2.2.4
   minikube -p higress-dev image load registry.local/higress/higress:2.2.4
   docker pull --platform linux/amd64 hashicorp/http-echo:1.0.0
   minikube -p higress-dev image load hashicorp/http-echo:1.0.0
   minikube -p higress-dev image load registry.local/higress/codex-request-block:2.2.4
   ```

3. 创建用于 xDS 实验的 namespace、回显后端、Service 和 Ingress（清单：[codex-xds-demo.yaml](../infra/minikube/codex-xds-demo.yaml)）；回显 Deployment 成功滚动至 1/1：

   ```bash
   kubectl --context higress-dev create namespace higress-system
   kubectl --context higress-dev apply -f infra/minikube/codex-xds-demo.yaml
   kubectl --context higress-dev -n higress-system rollout status deployment/codex-xds-echo --timeout=120s
   ```

4. 安装 Higress core 和 Console Helm release，两条命令返回 `STATUS: deployed`（Core chart 2.2.4、Console chart 2.1.0，Console 镜像由上面源码构建为 v2.2.4）：

   ```bash
   /home/teaho/.local/bin/helm install higress /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     --kube-context higress-dev -n higress-system -f infra/minikube/higress-values.yaml
   /home/teaho/.local/bin/helm install higress-console /home/teaho/IdeaProjects/agentspace/higress-console/helm \
     --kube-context higress-dev -n higress-system -f infra/minikube/console-values.yaml
   ```

5. 安装 Wasm 文件服务和插件 CR（清单：[codex-request-block.yaml](../infra/minikube/codex-request-block.yaml)），文件服务 Ready 且 Pod 内可访问 `main.wasm`：

   ```bash
   kubectl --context higress-dev apply -f infra/minikube/codex-request-block.yaml
   kubectl --context higress-dev -n higress-system rollout status deployment/codex-wasm-host --timeout=120s
   kubectl --context higress-dev -n higress-system exec deployment/codex-wasm-host -- \
     wget -q --spider http://127.0.0.1/main.wasm
   ```

6. Console 容器达到 1/1 Ready；通过 `kubectl port-forward service/higress-console 18081:8080` 后，请求 `http://127.0.0.1:18081/` 返回 `200 text/html`。回显 Service 从 Wasm 文件服务 Pod 内请求返回 `codex-xds-ok`：

   ```bash
   kubectl --context higress-dev -n higress-system port-forward service/higress-console 18081:8080 --address 127.0.0.1
   curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://127.0.0.1:18081/
   kubectl --context higress-dev -n higress-system exec deployment/codex-wasm-host -- \
     wget -qO- http://codex-xds-echo:5678/demo/ok
   ```

7. pilot 镜像载入后，`higress-controller` Pod 的 `higress-core` 与 `discovery` 两个容器均 Ready。两段配置快照都出现 `demo.local` 和 `codex-xds-demo`：

   ```bash
   kubectl --context higress-dev -n higress-system get pods -o wide
   kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c higress-core -- \
     curl -fsS 'http://127.0.0.1:8888/debug/configz?pretty' | rg -m 5 'codex-xds-demo|demo.local|codex-xds-echo'
   kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
     curl -fsS 'http://127.0.0.1:15014/debug/configz?pretty' | rg -m 5 'codex-xds-demo|demo.local|codex-xds-echo'
   ```

8. Gateway 镜像载入后，原 Pod 仍处在此前镜像缺失造成的拉取退避，因此重建 Deployment；新 Pod 达到 `1/1 Running`。三套主服务滚动状态均成功：

   ```bash
   kubectl --context higress-dev -n higress-system rollout restart deployment/higress-gateway
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-gateway --timeout=180s
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-controller --timeout=120s
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-console --timeout=120s
   kubectl --context higress-dev -n higress-system get deployments
   ```

9. Helm lint 均通过，release 均为 `deployed`：

   ```bash
   /home/teaho/.local/bin/helm lint /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     -f infra/minikube/higress-values.yaml
   /home/teaho/.local/bin/helm lint /home/teaho/IdeaProjects/agentspace/higress-console/helm \
     -f infra/minikube/console-values.yaml
   /home/teaho/.local/bin/helm list --kube-context higress-dev -n higress-system
   ```

10. Pod 运行的三个 Higress 镜像 ID 与本机构建摘要相同：controller `107c54a9`、pilot `88abc55a`、gateway `2ceb4611`；Console Pod 的镜像 ID 为本机 JAR 镜像 `201e8e1b`：

   ```bash
   kubectl --context higress-dev -n higress-system get pod -l app=higress-controller \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}={.imageID}{"\n"}{end}'
   kubectl --context higress-dev -n higress-system get pod -l app=higress-gateway \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}={.imageID}{"\n"}{end}'
   kubectl --context higress-dev -n higress-system get pod -l app.kubernetes.io/name=higress-console \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}={.imageID}{"\n"}{end}'
   ```

   最终五个 Deployment 全部 `1/1 Available`，五个 Pod 为 `Running` 且重启次数 0。主机 `free -h` 此时 `available` 约 26 GiB；`free` 列的 3 GiB 不代表只有 3 GiB 可用，文件缓存可回收。

11. Console 的 NodePort 直连地址由 Minikube 返回 `http://192.168.67.2:31378`，该地址请求实测 `200 text/html`，可直接从本机浏览器打开：

   ```bash
   minikube -p higress-dev service higress-console -n higress-system --url
   curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' \
     --max-time 10 http://192.168.67.2:31378/
   ```

### 4. xDS 下发与 Gateway 验证

1. pilot `/debug/connections` 返回 `totalClients:1`，客户端为 `higress-gateway-...higress-system-2`。Envoy `config_dump` 中同时存在 `demo.local` 监听路由、`codex-xds-echo` 上游集群和 `codex-request-block` Wasm 扩展：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
     curl -fsS 'http://127.0.0.1:15014/debug/connections'
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/config_dump' | \
     rg -m 12 'demo.local|codex-xds-echo|codex-request-block|codex-wasm-host|main.wasm'
   ```

2. Envoy `/stats` 实测 `higress-rds-80.demo.local.update_success` 为正数，`update_rejected: 0`；LDS 更新成功且拒绝数 0。Gateway 访问测试路由返回 `200` 与 `codex-xds-ok`；Console Ingress 返回 `200 text/html`：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'higress-rds-80.demo.local.(update_success|update_rejected):|listener_manager.lds.(update_success|update_rejected):'
   curl -sS -i --max-time 10 -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok
   curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' --max-time 10 \
     -H 'Host: console.higress.io' http://127.0.0.1:18080/
   ```

3. 再做一次真正的**动态 xDS 推送**：只改 Ingress 的 `host`，不重启组件。新域名 `demo2.local` 变为 200，旧域名 `demo.local` 变为 404；改回后状态反转，最终清单与运行状态恢复 `demo.local`：

   ```bash
   kubectl --context higress-dev -n higress-system patch ingress codex-xds-demo --type=json \
     -p='[{"op":"replace","path":"/spec/rules/0/host","value":"demo2.local"}]'
   # 等待数秒直至配置下发：
   curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: demo2.local' http://127.0.0.1:18080/demo/ok  # 200
   curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok   # 404
   kubectl --context higress-dev -n higress-system patch ingress codex-xds-demo --type=json \
     -p='[{"op":"replace","path":"/spec/rules/0/host","value":"demo.local"}]'
   # 等待数秒直至配置下发：
   curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok   # 200
   curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: demo2.local' http://127.0.0.1:18080/demo/ok  # 404
   ```

### 5. Wasm 插件

1. Gateway Pod 从集群内的 Wasm 文件服务拿到 `200` 和 `6630522` 字节；Envoy ECDS 中该插件的 `update_success: 2`，`config_fail: 0`、`update_rejected: 0`：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS -o /dev/null -w '%{http_code} %{size_download}\n' \
       http://codex-wasm-host.higress-system.svc.cluster.local/main.wasm
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'extension_config_discovery.http_filter.extensions.istio.io/wasmplugin/higress-system.codex-request-block.(update_success|update_rejected|config_fail):'
   ```

2. 插件配置在 [codex-request-block.yaml](../infra/minikube/codex-request-block.yaml) 中声明 `block_urls: [/demo/blocked]`。相同 Host 和后端，普通路径为 `200 codex-xds-ok`，屏蔽路径为 `403 codex-wasm-blocked`；Gateway access log 中 `response_code_details` 精确为 `via_wasm::higress-system.codex-request-block::request-block.url_blocked.keyword`，证明不是后端返回的 403：

   ```bash
   curl -sS -i --max-time 10 -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok
   curl -sS -i --max-time 10 -H 'Host: demo.local' http://127.0.0.1:18080/demo/blocked
   kubectl --context higress-dev -n higress-system logs deployment/higress-gateway -c higress-gateway --tail=150 | \
     rg 'request-block.url_blocked.keyword'
   ```

## 调试手册：xDS、Gateway、Wasm

在此环境始终显式指定 `--context higress-dev`，以免误查其他 Kubernetes 集群。路径在当前 Helm release 下依次是：Kubernetes Ingress/Service/WasmPlugin → `higress-core` 配置快照 `:8888` → `discovery`/pilot 配置快照与 ADS 连接 `:15014` → Gateway Envoy `:15000` → 真实 HTTP 请求。

先确认资源与后端。下面是一套可直接复制的逐段检查命令：

```bash
kubectl --context higress-dev -n higress-system get pods,ingress,service,wasmplugin
kubectl --context higress-dev -n higress-system get endpoints codex-xds-echo

# 第一段：controller 已把 Kubernetes 资源翻译成配置。
kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c higress-core -- \
  curl -fsS 'http://127.0.0.1:8888/debug/configz?pretty' | rg 'demo.local|codex-request-block'

# 第二段：pilot 已收到配置，且至少连接一个 Gateway ADS 客户端。
kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
  curl -fsS 'http://127.0.0.1:15014/debug/configz?pretty' | rg 'demo.local|codex-request-block'
kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
  curl -fsS 'http://127.0.0.1:15014/debug/connections'

# 第三段：Envoy 已收到 RDS/CDS/Wasm，并且没有 NACK。
kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
  curl -fsS 'http://127.0.0.1:15000/config_dump' | rg 'demo.local|codex-xds-echo|codex-request-block'
kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
  curl -fsS 'http://127.0.0.1:15000/stats' | rg 'update_(success|rejected):|config_fail:'

# 第四段：真实入口流量和 Wasm 行为。
curl -sS -i -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok
curl -sS -i -H 'Host: demo.local' http://127.0.0.1:18080/demo/blocked
kubectl --context higress-dev -n higress-system logs deployment/higress-gateway -c higress-gateway --tail=100 | \
  rg 'response_code_details'
```

第一段没有路由时，检查 Ingress 的 `ingressClassName: higress`、namespace、CRD 和 `higress-core` 日志。第一段有而第二段没有时，检查 controller 到 pilot 的配置传递；`totalClients:0` 时查 Gateway 到 `higress-controller:15012` 的连接、证书及 `discovery` 日志。第二段有而 Envoy 没有时，重点查 ADS/NACK 和版本兼容。Envoy 已有路由但返回 404 时核对 Host 与路径；503 时查看后端 endpoints 和 Envoy `/clusters`。Wasm 不生效时先核对文件 URL 的 `200`、ECDS 的 `config_fail/update_rejected`，再查 Gateway 日志；实测屏蔽请求日志的 `response_code_details` 为 `via_wasm::higress-system.codex-request-block::request-block.url_blocked.keyword`。

此示例清理由下列两条命令完成（**本次未执行，以保留可复验的运行环境**）：

```bash
kubectl --context higress-dev delete -f infra/minikube/codex-request-block.yaml
kubectl --context higress-dev delete -f infra/minikube/codex-xds-demo.yaml
```
