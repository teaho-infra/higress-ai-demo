# Higress 源码镜像、Minikube 与 xDS/Wasm 实跑记录（Codex）

> 本文记录 2026-09-28 在 `teaho-ThinkPad-E14-Gen-2` 上**实际执行且验证成功**的命令。旧计划中的命令仅作参考，不自动视为本机已成功。命令以本机用户 `teaho` 执行，除非明确注明。

## 目标与验收

- 固定 Higress 和 Higress Console 源码版本 v2.2.4，构建 controller、pilot、gateway、console 镜像。Gateway 使用源码组装的数据面镜像；若 Envoy 二进制取官方预编译产物，会明确记录。
- 用 Docker driver 启动独立的 Minikube 单节点集群，Helm 部署 `higress-system` 中的 core 和 console。
- 用真实 Ingress 证明 controller → pilot → gateway 的 xDS 配置下发，以 Envoy `config_dump` 和 HTTP 响应双重验证。
- 从 Higress 源码编译 `request-block`、`key-auth`、`ai-proxy` Wasm 插件，打包并推送 OCI 镜像到 Minikube 内的 Registry，通过 `oci://` 部署，证明插件配置下发与实际执行；使用本地 OpenAI 兼容模拟服务验证 AI 请求，不需要真实模型 API Key。
- 用带 Basic Auth 的独立私有 OCI Registry 和 `imagePullSecret` 再验证 `key-auth` 插件的存储、认证拉取及 Gateway 冷启动。

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
| 镜像构建 | 完成 | Controller `107c54a9`、pilot `88abc55a`、gateway `2ceb4611`、Console `201e8e1b`；源码 Wasm OCI 镜像 request-block `4a425fd2`、key-auth `ac92cec0`、ai-proxy `3534ffbd` |
| Minikube 与 Helm 部署 | 完成 | `higress-dev` 节点 Ready；两套 Helm release 为 `deployed`；Controller、Gateway、Console、回显后端、OCI Registry 均 Ready，旧 HTTP Wasm 服务缩为 0 |
| xDS 与 gateway 验证 | 完成 | controller、pilot、Envoy 三段可见路由；ADS 客户端 1 个；路由更新后新域名 200、旧域名 404，恢复亦成功 |
| Wasm 插件验证 | 完成 | 三个 `oci://` 镜像从集群 Registry 拉取；request-block 允许路径 200、屏蔽路径 403；key-auth 无 Key 401、错误 Key 403、正确 Key 200；ai-proxy 把 `demo-model` 映射为 `mock-model`，上游收到 `Bearer mock-upstream-token`，模拟响应 200；ECDS 拒绝 0 |
| 私有 Wasm Registry | 完成 | 独立 Registry 绑定 1 GiB PVC；匿名访问镜像 401、认证访问 200；`imagePullSecret` 使 Gateway 冷启动后再次认证拉取 `key-auth`，私有路由无 Key 401、错 Key 403、对 Key 200 |

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

本节是首次使用集群内 HTTP 文件服务验证 Wasm 代码能执行的过程；**最终部署方式已改为下一章的 OCI 插件镜像**。

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

## Wasm 源码打包为 OCI 镜像并部署（request-block）

前面的 HTTP 文件服务只用于先验证 `.wasm` 能执行。本节继续把同一个 Higress v2.2.4 源码插件封装为标准 OCI 镜像，推入 Minikube 集群内的 Registry，并让 Gateway 通过 `oci://` 拉取。以下命令均已在本机执行成功；终端 A 的 `port-forward` 在推送完成后已按 `Ctrl+C` 停止。

1. **重新从源码编译并打包插件。**Higress 源码 commit 为 `58666ac985cee19a0a9a353421c63cead6d0cb47`。在 `/home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/examples/request-block` 执行：

   ```bash
   git rev-parse HEAD
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=2 \
     GOOS=wasip1 GOARCH=wasm \
     go build -buildmode=c-shared -o main.wasm .
   sha256sum main.wasm
   file main.wasm
   docker build --platform linux/amd64 -t localhost:15005/request-block:2.2.4 -f Dockerfile .
   docker image inspect localhost:15005/request-block:2.2.4 --format '{{.Id}} {{.Size}}'
   ```

   `main.wasm` 是 WebAssembly MVP 模块，SHA-256 为 `7a1ff2e43b06c3d8e7b57e241abd88282b7553b736e9b57c3a985b8b62112eb0`。直接使用**源码自带**的 `examples/request-block/Dockerfile`（`FROM scratch`，将 `main.wasm` 复制为 `/plugin.wasm`），得到镜像 `sha256:4a425fd2c26475c816997850768575e1d52e5bdc0744876f5ac4bc6733ffa087`，大小 `6630522` 字节。它不是前文用于 HTTP 文件服务的 nginx 镜像。

2. **在 Minikube 内部署持久化 OCI Registry。**清单为 [codex-wasm-registry.yaml](../infra/minikube/codex-wasm-registry.yaml)，包含 `registry:2.8.3`、ClusterIP Service 和 1 GiB PVC。在仓库 `/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo` 执行：

   ```bash
   docker pull --platform linux/amd64 registry:2.8.3
   minikube -p higress-dev image load registry:2.8.3
   kubectl --context higress-dev apply -f infra/minikube/codex-wasm-registry.yaml
   kubectl --context higress-dev -n higress-system rollout status deployment/codex-wasm-registry --timeout=120s
   kubectl --context higress-dev -n higress-system get pvc codex-wasm-registry-data
   ```

   Registry Pod 为 `1/1 Running`，PVC 为 `Bound`。Service 只在集群内暴露 `:5000`。

3. **通过临时端口转发从宿主机推送 OCI 镜像。**终端 A 运行下列命令，保持它运行至 `docker push` 完成：

   ```bash
   kubectl --context higress-dev -n higress-system port-forward \
     service/codex-wasm-registry 15005:5000 --address 127.0.0.1
   ```

   终端 B 在插件源码目录运行：

   ```bash
   curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:15005/v2/
   docker push localhost:15005/request-block:2.2.4
   curl -fsS -o /dev/null -w 'manifest=%{http_code} bytes=%{size_download}\n' \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
     http://127.0.0.1:15005/v2/request-block/manifests/2.2.4
   ```

   `/v2/` 返回 `200`，推送摘要为 `sha256:b20aee4b2cd965ebf7710d299adf851440332909a1892d0582dd0b5a408b4deb`，Manifest 返回 `200`、`527` 字节。`localhost:15005` 只是宿主机推送入口；Gateway 拉取同一 Registry 的集群 Service 地址。在仓库目录从 Gateway 容器测试 Service 也返回 `200`：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS -o /dev/null -w 'registry=%{http_code}\n' \
       http://codex-wasm-registry.higress-system.svc.cluster.local:5000/v2/
   ```

4. **让 Gateway 只允许该本地 HTTP Registry。**[higress-values.yaml](../infra/minikube/higress-values.yaml) 的 `gateway.env.WASM_INSECURE_REGISTRIES` 已设为 `codex-wasm-registry.higress-system.svc.cluster.local:5000`。在仓库目录执行，Core Helm release 升到 revision 2，Gateway 完成滚动更新：

   ```bash
   /home/teaho/.local/bin/helm lint /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     -f infra/minikube/higress-values.yaml
   /home/teaho/.local/bin/helm upgrade higress /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     --kube-context higress-dev -n higress-system \
     -f infra/minikube/higress-values.yaml --wait --timeout=3m
   kubectl --context higress-dev -n higress-system get deployment higress-gateway \
     -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="WASM_INSECURE_REGISTRIES")].value}{"\n"}'
   ```

5. **将插件 CR 切到 OCI 镜像。**[codex-request-block-oci.yaml](../infra/minikube/codex-request-block-oci.yaml) 保留原屏蔽规则，将 `spec.url` 改为 `oci://codex-wasm-registry.higress-system.svc.cluster.local:5000/request-block:2.2.4`。在仓库目录执行：

   ```bash
   kubectl --context higress-dev apply -f infra/minikube/codex-request-block-oci.yaml
   kubectl --context higress-dev -n higress-system get wasmplugin codex-request-block \
     -o jsonpath='{.spec.url}{"\n"}'
   kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
     curl -fsS 'http://127.0.0.1:15014/debug/configz?pretty' | rg -m 3 'oci://codex-wasm-registry'
   kubectl --context higress-dev -n higress-system logs deployment/higress-gateway -c higress-gateway --since=2m | \
     rg 'fetching image request-block'
   kubectl --context higress-dev -n higress-system logs deployment/codex-wasm-registry -c registry --since=3m | \
     rg 'GET /v2/request-block/(manifests|blobs)' | tail -n 10
   ```

   pilot 配置快照中出现 OCI URL；Gateway 日志写明从 `codex-wasm-registry...:5000` 拉取 tag `2.2.4`；Registry 日志显示 Gateway Pod 对 Manifest 与 Blob 的请求均为 `200`。Envoy ECDS 中 `codex-request-block.update_success: 3`、`config_fail: 0`、`update_rejected: 0`：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'extension_config_discovery.http_filter.extensions.istio.io/wasmplugin/higress-system.codex-request-block.(update_success|update_rejected|config_fail):'
   ```

6. **停用旧 HTTP 文件服务，重启 Gateway 做冷启动验证。**在仓库目录执行：

   ```bash
   kubectl --context higress-dev -n higress-system scale deployment/codex-wasm-host --replicas=0
   kubectl --context higress-dev -n higress-system rollout status deployment/codex-wasm-host --timeout=60s
   kubectl --context higress-dev -n higress-system rollout restart deployment/higress-gateway
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-gateway --timeout=180s
   curl -sS -o /dev/null -w 'allowed=%{http_code}\n' \
     -H 'Host: demo.local' http://127.0.0.1:18080/demo/ok
   curl -sS -o /dev/null -w 'blocked=%{http_code}\n' \
     -H 'Host: demo.local' http://127.0.0.1:18080/demo/blocked
   kubectl --context higress-dev -n higress-system logs deployment/higress-gateway -c higress-gateway --since=90s | \
     rg 'fetching image request-block|request-block.url_blocked.keyword'
   ```

   旧 HTTP 服务为 `0/0`，新 Gateway 为 `1/1`。重启后的 Gateway 再次记录 OCI 镜像拉取；普通请求为 `200`，屏蔽请求为 `403`，Console 为 `200`，ECDS 再次显示 `update_success: 2`、`config_fail: 0`、`update_rejected: 0`；access log 的 `response_code_details` 仍为 `via_wasm::higress-system.codex-request-block::request-block.url_blocked.keyword`。端口转发停止后这些状态码仍保持，因此最终运行不依赖旧 HTTP 文件服务，也不依赖宿主机的临时推送端口。

## 源码打包并验证 key-auth 与 ai-proxy

继续使用上一章已部署的 `higress-dev`、OCI Registry 和 `WASM_INSECURE_REGISTRIES`。两个插件都来自同一个 Higress v2.2.4 源码树，镜像中的 `/plugin.wasm` 均由本机编译。示例使用 [codex-ai-key-demo.yaml](../infra/minikube/codex-ai-key-demo.yaml) 中的本地模拟 OpenAI 上游；`codex-local-example-key` 和 `mock-upstream-token` 只是演示值，不是线上凭证，也不调用真实模型。以下命令和 HTTP 结果均已在本机验证。

1. **从源码编译两个 Wasm 模块。**分别在对应源码目录执行相同的构建命令：

   ```bash
   cd /home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/examples/key-auth
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=2 \
     GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o main.wasm .
   file main.wasm
   sha256sum main.wasm

   cd /home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/extensions/ai-proxy
   env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
     PATH=/home/teaho/tools/go1.26.0/bin:$PATH \
     GOPROXY='https://goproxy.cn|https://proxy.golang.org' \
     GOMODCACHE=/home/teaho/.cache/higress-go-mod GOMAXPROCS=2 \
     GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o main.wasm .
   file main.wasm
   sha256sum main.wasm
   ```

   两者均识别为 WebAssembly 模块。`key-auth` 的 Wasm SHA-256 为 `df9602dc42e00423a49abd94a146c453906dd81c1cd6ab2e03d69b3e29eb10b8`，`ai-proxy` 为 `424709692ab1edee33ea188ef0b27e40ea096a4c22e29520e3aeaab09e88e8be`。

2. **打包为 OCI 镜像并推送集群 Registry。**[Dockerfile.wasm-oci-codex](../infra/minikube/Dockerfile.wasm-oci-codex) 只有 `FROM scratch` 和 `COPY main.wasm /plugin.wasm`。先在终端 A 保持端口转发（若上一章的会话已经停止，则重新运行）：

   ```bash
   kubectl --context higress-dev -n higress-system port-forward \
     service/codex-wasm-registry 15005:5000 --address 127.0.0.1
   ```

   终端 B 运行：

   ```bash
   docker build --platform linux/amd64 \
     -t localhost:15005/key-auth:2.2.4 \
     -f /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/Dockerfile.wasm-oci-codex \
     /home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/examples/key-auth
   docker build --platform linux/amd64 \
     -t localhost:15005/ai-proxy:2.2.4 \
     -f /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/Dockerfile.wasm-oci-codex \
     /home/teaho/IdeaProjects/agentspace/higress/plugins/wasm-go/extensions/ai-proxy
   docker image inspect localhost:15005/key-auth:2.2.4 --format '{{.Id}} {{.Size}}'
   docker image inspect localhost:15005/ai-proxy:2.2.4 --format '{{.Id}} {{.Size}}'
   docker push localhost:15005/key-auth:2.2.4
   docker push localhost:15005/ai-proxy:2.2.4
   curl -fsS -o /dev/null -w 'key-auth manifest=%{http_code}\n' \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
     http://127.0.0.1:15005/v2/key-auth/manifests/2.2.4
   curl -fsS -o /dev/null -w 'ai-proxy manifest=%{http_code}\n' \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
     http://127.0.0.1:15005/v2/ai-proxy/manifests/2.2.4
   ```

   本机镜像 ID 分别为 `sha256:ac92cec0...`、`sha256:3534ffbd...`；推送后 Registry 摘要分别为 `sha256:632f1f2894f03f25e49623290bc9e31fd11829508eafe9cf12f2ea5a84ef5051`、`sha256:e27df3903d0ced50e391542d77eb5a4e9c7d3976354793107b5ccd520801464b`。两个 Manifest 查询均为 `200`。推送完成后可在终端 A 用 `Ctrl+C` 关闭端口转发；Gateway 始终通过集群 Service 拉取镜像。

3. **部署本地上游、路由和插件。**模拟服务只接受 `/v1/chat/completions`，回显收到的模型名、Host、Authorization 和鉴权消费者；支持 `Content-Length` 与 chunked 请求体。为离线启动先载入 `python:3.12-alpine`。在 `/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo` 执行：

   ```bash
   cd /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo
   docker pull --platform linux/amd64 python:3.12-alpine
   minikube -p higress-dev image load python:3.12-alpine
   kubectl --context higress-dev apply --dry-run=server -f infra/minikube/codex-ai-key-demo.yaml
   kubectl --context higress-dev apply -f infra/minikube/codex-ai-key-demo.yaml
   kubectl --context higress-dev -n higress-system rollout status deployment/codex-ai-mock --timeout=90s
   kubectl --context higress-dev -n higress-system get ingress codex-key-auth-demo codex-ai-proxy-demo
   kubectl --context higress-dev -n higress-system get wasmplugin codex-key-auth codex-ai-proxy
   ```

   清单定义 `auth.local/auth` 到回显后端、`ai.local/v1/chat/completions` 到本地 OpenAI 兼容上游。`key-auth` 仅对 `auth.local` 和 `ai.local` 生效；`ai-proxy` 仅对 `ai.local` 生效。两者用 `matchRules.domain` 匹配 Host。曾尝试用带命名空间前缀的 `matchRules.ingress`，插件配置虽成功下发但该环境的网关路由名为无前缀的 `codex-key-auth-demo` 等，实际请求未命中规则；改为域名匹配后鉴权正常。

4. **检查 xDS/ECDS 已下发且镜像已加载。**下面命令在本机看到 `codex-key-auth`、`codex-ai-proxy` 的 OCI URL 与 ECDS 配置；两者 `update_success` 为正数，`config_fail` 和 `update_rejected` 为 0。Registry 日志显示 Gateway 对两镜像的 Manifest 和 Blob 均取得 `200`：

   ```bash
   kubectl --context higress-dev -n higress-system exec deployment/higress-controller -c discovery -- \
     curl -fsS 'http://127.0.0.1:15014/debug/configz?pretty' | \
     rg -m 4 'codex-key-auth|codex-ai-proxy'
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/config_dump' | \
     rg -m 4 'codex-key-auth|codex-ai-proxy'
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'extension_config_discovery.*codex-(key-auth|ai-proxy).*(update_success|config_fail|update_rejected):'
   kubectl --context higress-dev -n higress-system logs deployment/codex-wasm-registry -c registry --since=15m | \
     rg 'GET /v2/(key-auth|ai-proxy)/(manifests|blobs)' | tail -n 12
   ```

5. **验证 key-auth 的拒绝和放行。**这些是实际经过 Gateway NodePort 的请求，不是直接调用上游：

   ```bash
   curl -sS -i -H 'Host: auth.local' \
     http://127.0.0.1:18080/auth/test
   curl -sS -i -H 'Host: auth.local' -H 'x-api-key: wrong-key' \
     http://127.0.0.1:18080/auth/test
   curl -sS -i -H 'Host: auth.local' -H 'x-api-key: codex-local-example-key' \
     http://127.0.0.1:18080/auth/test
   ```

   实际返回依次为 `401`（无 Key）、`403`（消费者未授权）、`200 codex-xds-ok`（正确 Key）。Gateway access log 的拒绝原因分别为 `via_wasm::higress-system.codex-key-auth::key-auth.no_key` 和 `via_wasm::higress-system.codex-key-auth::key-auth.unauthorized`。

6. **验证两个插件在 AI 路由上协同工作。**未带 Key 的请求被 `key-auth` 拒绝；带演示 Key 的请求经过 `ai-proxy`，模拟上游收到映射后的模型名和配置的 Bearer token：

   ```bash
   curl -sS -i -H 'Host: ai.local' -H 'Content-Type: application/json' \
     --data '{"model":"demo-model","messages":[{"role":"user","content":"hi"}]}' \
     http://127.0.0.1:18080/v1/chat/completions
   curl -sS -i -H 'Host: ai.local' -H 'Content-Type: application/json' \
     -H 'x-api-key: codex-local-example-key' \
     --data '{"model":"demo-model","messages":[{"role":"user","content":"hi"}]}' \
     http://127.0.0.1:18080/v1/chat/completions
   ```

   首个请求实测 `401`。第二个返回 `200`，JSON 中 `model: "mock-model"`、`choices[0].message.content: "mock-ai-ok"`，`codex_debug.authorization: "Bearer mock-upstream-token"`、`codex_debug.consumer: "codex-demo"`，同时上游看到 `Host: codex-ai-mock.higress-system.svc.cluster.local`。这验证本地模拟上游的协议转换、模型映射、上游 Token 和鉴权上下文；**没有验证真实 AI 服务提供商的调用或账单**。

7. **关闭宿主机 Registry 端口转发后做冷启动复验。**在终端 A 停止第 2 步的 `port-forward`，再执行：

   ```bash
   kubectl --context higress-dev -n higress-system rollout restart deployment/higress-gateway
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-gateway --timeout=180s
   kubectl --context higress-dev -n higress-system logs deployment/higress-gateway -c higress-gateway --since=3m | \
     rg 'fetching image (key-auth|ai-proxy)'
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'extension_config_discovery.*codex-(key-auth|ai-proxy).*(update_success|config_fail|update_rejected):'
   curl -sS -o /dev/null -w 'no-key=%{http_code}\n' -H 'Host: auth.local' \
     http://127.0.0.1:18080/auth/test
   curl -sS -o /dev/null -w 'valid-key=%{http_code}\n' -H 'Host: auth.local' \
     -H 'x-api-key: codex-local-example-key' http://127.0.0.1:18080/auth/test
   curl -sS -H 'Host: ai.local' -H 'Content-Type: application/json' \
     -H 'x-api-key: codex-local-example-key' \
     --data '{"model":"demo-model","messages":[{"role":"user","content":"hi"}]}' \
     http://127.0.0.1:18080/v1/chat/completions
   ```

   新 Gateway 再次从集群 Service 拉取两个 OCI 镜像；Registry 的 Manifest/Blob 均为 `200`。两插件的 `update_success: 2`、`config_fail: 0`、`update_rejected: 0`；冷启动后的无 Key 请求仍为 `401`、正确 Key 为 `200`、AI 模拟请求为 `200` 且模型/Token 映射保持正确。原 `request-block` 路由也保持允许路径 `200`、屏蔽路径 `403`。

## 带认证的私有 OCI Registry 再验证 Wasm

2026-09-29 本机 `MemAvailable` 约 24 GiB，`higress-dev` 与原有服务均为 Ready，因此在同一 Minikube 中增加一套**独立** Registry，不改动上一章的公开演示 Registry。这里的“私有”指集群内 Service + PVC 存储 + Registry Basic Auth + Higress `imagePullSecret`；使用 HTTP 仅限这台本机的 Minikube 实验。生产环境还需要可信 TLS、独立凭据管理和存储备份。密码随机生成，仅进入临时本机文件和 Kubernetes Secret，不写入 Git。

1. **生成 Registry 认证与插件拉取 Secret。**Registry 2.8.3 在本机验证中使用 bcrypt 格式的 htpasswd；APR1 格式会使带密码请求也返回 `401`。在仓库目录执行：

   ```bash
   cd /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo
   install -d -m 700 /tmp/higress-private-wasm-demo
   umask 077
   openssl rand -hex 24 > /tmp/higress-private-wasm-demo/password
   python3 - <<'PY'
   from pathlib import Path
   import bcrypt
   root = Path('/tmp/higress-private-wasm-demo')
   password = root.joinpath('password').read_bytes().strip()
   root.joinpath('htpasswd').write_bytes(
       b'codex-wasm:' + bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)) + b'\n'
   )
   PY
   kubectl --context higress-dev -n higress-system create secret generic codex-private-wasm-htpasswd \
     --from-file=htpasswd=/tmp/higress-private-wasm-demo/htpasswd \
     --dry-run=client -o yaml | kubectl --context higress-dev apply -f -
   kubectl --context higress-dev -n higress-system create secret docker-registry codex-private-wasm-pull \
     --docker-server=codex-private-wasm-registry.higress-system.svc.cluster.local:5000 \
     --docker-username=codex-wasm \
     --docker-password="$(cat /tmp/higress-private-wasm-demo/password)" \
     --dry-run=client -o yaml | kubectl --context higress-dev apply -f -
   kubectl --context higress-dev -n higress-system get secret codex-private-wasm-pull \
     -o jsonpath='{.type}{"\n"}'
   ```

   拉取 Secret 的类型实测为 `kubernetes.io/dockerconfigjson`。`WasmPlugin.spec.imagePullSecret` 引用的 Secret 必须与插件 CR 同在 `higress-system`；它不同于 Gateway Pod 的 `imagePullSecrets`。

2. **部署独立持久化 Registry。**[codex-private-wasm-registry.yaml](../infra/minikube/codex-private-wasm-registry.yaml) 包含 `registry:2.8.3`、集群内 Service 和 1 GiB PVC，挂载上一步的 htpasswd Secret。由于匿名 `/v2/` 正常返回 `401`，这里用 TCP readiness probe。执行：

   ```bash
   kubectl --context higress-dev apply -f infra/minikube/codex-private-wasm-registry.yaml
   kubectl --context higress-dev -n higress-system rollout status \
     deployment/codex-private-wasm-registry --timeout=120s
   kubectl --context higress-dev -n higress-system get pvc codex-private-wasm-registry-data
   ```

   Deployment 为 `1/1`，PVC 为 `Bound`。

3. **验证仓库认证并推送源码构建的 `key-auth` 镜像。**终端 A 保持运行：

   ```bash
   kubectl --context higress-dev -n higress-system port-forward \
     service/codex-private-wasm-registry 15006:5000 --address 127.0.0.1
   ```

   终端 B 执行：

   ```bash
   curl -sS -o /dev/null -w 'anonymous=%{http_code}\n' http://127.0.0.1:15006/v2/
   curl -sS -o /dev/null -w 'authenticated=%{http_code}\n' \
     -u "codex-wasm:$(cat /tmp/higress-private-wasm-demo/password)" \
     http://127.0.0.1:15006/v2/
   install -d -m 700 /tmp/higress-private-wasm-demo/docker
   docker tag localhost:15005/key-auth:2.2.4 localhost:15006/key-auth:2.2.4
   cat /tmp/higress-private-wasm-demo/password | \
     docker --config /tmp/higress-private-wasm-demo/docker login localhost:15006 \
       --username codex-wasm --password-stdin
   docker --config /tmp/higress-private-wasm-demo/docker push localhost:15006/key-auth:2.2.4
   curl -sS -o /dev/null -w 'anonymous_manifest=%{http_code}\n' \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
     http://127.0.0.1:15006/v2/key-auth/manifests/2.2.4
   curl -sS -o /dev/null -w 'authenticated_manifest=%{http_code}\n' \
     -u "codex-wasm:$(cat /tmp/higress-private-wasm-demo/password)" \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
     http://127.0.0.1:15006/v2/key-auth/manifests/2.2.4
   ```

   `/v2/` 和 Manifest 均为匿名 `401`、认证后 `200`。镜像来自前一章本机编译的 `key-auth` Wasm，推送摘要 `sha256:632f1f2894f03f25e49623290bc9e31fd11829508eafe9cf12f2ea5a84ef5051`。终端 A 在推送后用 `Ctrl+C` 停止；临时 Docker 配置仅用于本机推送。

4. **部署 Higress 私有插件。**[higress-values.yaml](../infra/minikube/higress-values.yaml) 的 `WASM_INSECURE_REGISTRIES` 现同时列出两套集群内 HTTP Registry。[codex-private-key-auth.yaml](../infra/minikube/codex-private-key-auth.yaml) 给 `private.local/private` 路由配置独立的 `key-auth` WasmPlugin，并设置 `imagePullSecret: codex-private-wasm-pull`。执行：

   ```bash
   /home/teaho/.local/bin/helm lint /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     -f infra/minikube/higress-values.yaml
   /home/teaho/.local/bin/helm upgrade higress /home/teaho/IdeaProjects/agentspace/higress/helm/core \
     --kube-context higress-dev -n higress-system \
     -f infra/minikube/higress-values.yaml --wait --timeout=3m
   kubectl --context higress-dev apply -f infra/minikube/codex-private-key-auth.yaml
   kubectl --context higress-dev -n higress-system get wasmplugin codex-private-key-auth \
     -o jsonpath='{.spec.imagePullSecret}{" "}{.spec.url}{"\n"}'
   ```

   Helm core 为 `deployed`（revision 3），插件 CR 指向私有 Service 的 OCI URL。Gateway 日志出现 `fetching image key-auth from registry codex-private-wasm-registry...:5000`；Registry 日志显示 Gateway Pod **认证成功**，Manifest 和 Blob 均返回 `200`。Envoy ECDS 的该插件 `update_success: 2`、`config_fail: 0`、`update_rejected: 0`。

5. **真实入口与冷启动验证。**停掉终端 A 的端口转发后执行：

   ```bash
   kubectl --context higress-dev -n higress-system rollout restart deployment/higress-gateway
   kubectl --context higress-dev -n higress-system rollout status deployment/higress-gateway --timeout=180s
   curl -sS -i -H 'Host: private.local' http://127.0.0.1:18080/private/test
   curl -sS -i -H 'Host: private.local' -H 'x-api-key: wrong-key' \
     http://127.0.0.1:18080/private/test
   curl -sS -i -H 'Host: private.local' -H 'x-api-key: codex-private-example-key' \
     http://127.0.0.1:18080/private/test
   kubectl --context higress-dev -n higress-system exec deployment/higress-gateway -c higress-gateway -- \
     curl -fsS 'http://127.0.0.1:15000/stats' | \
     rg 'extension_config_discovery.*codex-private-key-auth.*(update_success|update_rejected|config_fail):'
   kubectl --context higress-dev -n higress-system logs deployment/codex-private-wasm-registry -c registry --since=3m | \
     rg 'GET /v2/key-auth/(manifests|blobs)' | tail -n 6
   ```

   冷启动后私有路由依次返回 `401`、`403`、`200 codex-xds-ok`；Registry 再次记录新 Gateway Pod 对 Manifest/Blob 的认证拉取，ECDS 拒绝和配置失败均为 0。原 `request-block` 仍返回预期的 `403`，`ai-proxy` 模拟请求仍返回映射后的模型与 Token。可以删除本机临时密码和 Docker 配置，集群中的两个 Secret 不受影响：

   ```bash
   python3 - <<'PY'
   from pathlib import Path
   root = Path('/tmp/higress-private-wasm-demo')
   for name in ('password', 'htpasswd'):
       root.joinpath(name).unlink(missing_ok=True)
   (root / 'docker' / 'config.json').unlink(missing_ok=True)
   (root / 'docker').rmdir()
   root.rmdir()
   PY
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

第一段没有路由时，检查 Ingress 的 `ingressClassName: higress`、namespace、CRD 和 `higress-core` 日志。第一段有而第二段没有时，检查 controller 到 pilot 的配置传递；`totalClients:0` 时查 Gateway 到 `higress-controller:15012` 的连接、证书及 `discovery` 日志。第二段有而 Envoy 没有时，重点查 ADS/NACK 和版本兼容。Envoy 已有路由但返回 404 时核对 Host 与路径；503 时查看后端 endpoints 和 Envoy `/clusters`。最终 OCI 方式下 Wasm 不生效时，先核对 Registry PVC/Pod、`/v2/` 与镜像 Manifest 是否可达，再核对 Gateway 的 `WASM_INSECURE_REGISTRIES`、Registry 的 Manifest/Blob 访问日志、ECDS 的 `config_fail/update_rejected` 和 Gateway 拉取日志。若 ECDS 成功而 `key-auth` 无 Key 请求仍是 200，检查 ECDS 配置中的 `_match_domain_` 或 `_match_route_` 是否与真实 Host/Envoy 路由名一致；此环境用域名规则成功命中。实测拒绝请求的 `response_code_details` 包括 `via_wasm::higress-system.codex-key-auth::key-auth.no_key` 和 `via_wasm::higress-system.codex-request-block::request-block.url_blocked.keyword`。

此示例可由下列命令清理（**本次未执行，以保留可复验的运行环境**）：

```bash
kubectl --context higress-dev delete -f infra/minikube/codex-private-key-auth.yaml
kubectl --context higress-dev delete -f infra/minikube/codex-private-wasm-registry.yaml
kubectl --context higress-dev -n higress-system delete secret codex-private-wasm-htpasswd codex-private-wasm-pull
kubectl --context higress-dev delete -f infra/minikube/codex-ai-key-demo.yaml
kubectl --context higress-dev delete -f infra/minikube/codex-request-block-oci.yaml
kubectl --context higress-dev -n higress-system delete deployment/codex-wasm-host service/codex-wasm-host
kubectl --context higress-dev delete -f infra/minikube/codex-wasm-registry.yaml
kubectl --context higress-dev delete -f infra/minikube/codex-xds-demo.yaml
```
