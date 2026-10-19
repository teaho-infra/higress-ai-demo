# Higress v2.2.5 企业私有化源码镜像构建

> **历史方案，已由源码仓库中的新版替代。** 请使用 [Higress 企业构建指引](https://github.com/teaho-infra/higress/blob/ft/v2.2.5-teaho/docs/walmart/README.md) 和 [本地验证记录](https://github.com/teaho-infra/higress/blob/ft/v2.2.5-teaho/docs/walmart/verification.md)。新版独立使用 Go 1.23/bullseye 编译 Go filter，已于 2026-10-19 完成 higress-core、discovery、higress-gateway 三个镜像构建及 Envoy/Go filter/HTTP 200 验证。下文和本目录 Dockerfile 保留旧方案与失败记录，不作为当前执行入口。

**① 准备基础镜像 → ② 准备离线文件 → ③ 准备源码与 Dockerfile → ④ 编译镜像。**

源码目录：`/home/teaho/IdeaProjects/teaho-infra/higress`。适用于 Linux/amd64。参考此前 [本地成功构建记录](minikube-source-build-cluster-codex.md) 的 base/build-tools、离线 Envoy 和 Go filter 构建方式，替换为企业 Harbor 和公司 Go 代理。

| 服务 | 使用的 Dockerfile（均包含编译和运行阶段） | 输出镜像 |
| --- | --- | --- |
| Controller 控制面 | [Dockerfile.controller](../infra/private-build/Dockerfile.controller) | `controller:2.2.5-walmart`、`discovery:2.2.5-walmart` |
| Gateway 数据面 | [Dockerfile.gateway](../infra/private-build/Dockerfile.gateway) | `gateway:2.2.5-walmart` |

Controller Deployment 有 `higress-core`、`discovery` 两个容器，因此两个服务共需三个镜像。controller、pilot-discovery、pilot-agent、golang-filter.so 从源码编译；**Envoy 使用官方 v2.2.5 预编译产物，不重新编译 Envoy C++**，与此前成功构建的范围一致。

下面的下载和导入由你手动执行。企业 Docker 构建过程只访问 **Harbor + 公司 GOPROXY**，不访问阿里、GitHub 或外部 apt 源。2026-10-19 已在本机实际构建：controller、discovery 成功并通过启动入口检查；**gateway 尚未构建成功，Go filter 编译存在未解决的工具链内部错误**，详见 4.4。企业 Harbor/公司 GOPROXY、集群部署均未验证。

## ① 准备基础镜像

### 1.1 使用哪些镜像

这两个是真实引用自此前 plan 的官方镜像，不是虚构的 runtime 名称：

| 用途 | 阿里源镜像 | 导入 Harbor 后的建议地址 |
| --- | --- | --- |
| 运行基础 | `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64` | `harbor.qa.wal-mart.cn/base-image/higress-base:2023-07-20T20-50-43-amd64` |
| 编译环境 | `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613` | `harbor.qa.wal-mart.cn/base-image/higress-build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613` |

当前源码的 `HIGRESS_BASE_VERSION` 仍为上述 2023 标签，不应机械地改成 `base:2.2.5`。本方案需要 **base + build-tools**，无需先导入完整 controller/core/gateway 业务镜像，也不要将 core 成品镜像直接当作 base 替换。

build-tools 自带的 Go 较旧，步骤②会准备 Go 1.26.0，由 Dockerfile 覆盖工具链路径；Go filter 使用其 GCC/G++。运行 base 沿用官方 CA、用户及系统工具。建议保存实际镜像 digest，并按公司流程扫描这两个历史基础镜像；若更换基础版本，需重新准备离线系统依赖并验证兼容性。

### 1.2 中转机：拉取并导出

在**能访问阿里镜像源的中转机**执行，不是在受限企业构建机执行：

```bash
mkdir -p "$HOME/higress-enterprise-inputs"
cd "$HOME/higress-enterprise-inputs"
export ALI_BASE=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64
export ALI_BUILD_TOOLS=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613

docker pull --platform linux/amd64 "$ALI_BASE"
docker pull --platform linux/amd64 "$ALI_BUILD_TOOLS"
docker image inspect "$ALI_BASE" "$ALI_BUILD_TOOLS" \
  --format '{{.Id}} {{.Architecture}} {{json .RepoDigests}}'
docker save -o higress-base-and-build-tools.tar "$ALI_BASE" "$ALI_BUILD_TOOLS"
sha256sum higress-base-and-build-tools.tar > higress-base-and-build-tools.tar.sha256
```

把 tar 和 sha256 文件传入企业环境；中转机上保留这两个镜像，步骤②还会用到 base。

### 1.3 企业环境：导入并推送 Harbor

在收到 tar 的目录执行。目标 Harbor 项目需要存在，账号具有推送权限；地址可按公司规范调整。

```bash
sha256sum -c higress-base-and-build-tools.tar.sha256
docker load -i higress-base-and-build-tools.tar
docker login harbor.qa.wal-mart.cn

export BASE_IMAGE=harbor.qa.wal-mart.cn/base-image/higress-base:2023-07-20T20-50-43-amd64
export BUILD_TOOLS_IMAGE=harbor.qa.wal-mart.cn/base-image/higress-build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613

docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64 "$BASE_IMAGE"
docker tag higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613 "$BUILD_TOOLS_IMAGE"
docker push "$BASE_IMAGE"
docker push "$BUILD_TOOLS_IMAGE"
```

`docker load/tag` 使用本地镜像，不连接阿里。Harbor 使用公司 CA 时，先配置 Docker daemon/BuildKit 信任；这与 Wasm 插件的 `WASM_INSECURE_REGISTRIES` 无关。

## ② 准备离线文件（含 Envoy）

继续在中转机的 `$HOME/higress-enterprise-inputs` 中执行。准备三类文件：Go 工具链、Gateway 二进制、Gateway 系统依赖包。

### 2.1 Go、Envoy、supercronic

```bash
cd "$HOME/higress-enterprise-inputs"
mkdir -p offline/runtime-debs
curl -fL --retry 3 https://go.dev/dl/go1.26.0.linux-amd64.tar.gz \
  -o offline/go1.26.0.linux-amd64.tar.gz
curl -fL --retry 3 https://github.com/higress-group/proxy/releases/download/v2.2.5/envoy-symbol-amd64.tar.gz \
  -o offline/envoy-symbol-amd64.tar.gz
curl -fL --retry 3 https://github.com/higress-group/proxy/releases/download/v2.2.0/supercronic-linux-amd64 \
  -o offline/supercronic-linux-amd64
```

Envoy 的 v2.2.5 地址来自当前 `Makefile.core.mk`；supercronic 的 v2.2.0 地址来自当前官方 `Dockerfile.proxyv2`，不要随意改版本。本地根模块及 Istio 模块最低要求 Go 1.26.0，原有 Go 1.24.1 不能直接使用。

### 2.2 离线准备 logrotate、cron 及依赖

官方 base 不等于完整 Gateway 运行环境。官方 Gateway Dockerfile 还会安装 logrotate、cron；这里改为在中转机下载，企业构建时离线安装。

运行阶段使用 `dpkg -i /tmp/runtime-debs/*.deb` 安装完整依赖，不访问软件源。实际验证发现旧 base 的 `apt-get --no-download ... install /tmp/runtime-debs/*.deb` 会出现 `Pathname to install is not absolute` 内部错误，因此不使用该写法；缺少依赖时让构建失败，回中转机补齐包。

**必须使用步骤①同一个 base 镜像及架构解析依赖，不能在宿主机或其他发行版下载。**

```bash
export ALI_BASE=higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/base:2023-07-20T20-50-43-amd64
docker run --rm --platform linux/amd64 --user 0 \
  --entrypoint /bin/bash \
  -v "$PWD/offline/runtime-debs:/offline" \
  "$ALI_BASE" -ec '
    apt-get -o Acquire::Retries=3 update
    apt-get -o Acquire::Retries=3 install --download-only --no-install-recommends -y logrotate cron
    test -n "$(find /var/cache/apt/archives -maxdepth 1 -name "*.deb" -print -quit)"
    cp /var/cache/apt/archives/*.deb /offline/
    chmod a+r /offline/*.deb
  '
```

只复制 `.deb`，不要把 apt 的 `partial/`、`lock` 等缓存目录放入构建上下文；其权限可能导致 Docker 在编译前就报错。

此命令需要**中转机容器**能访问该 base 配置的 apt 源。若不可达，应在中转环境配置同发行版的软件源后重新下载完整依赖；企业构建机不需要 apt 网络。

### 2.3 记录摘要并转移 offline 目录

确认下载来源可信，Go 归档对照官方发布摘要，然后执行：

```bash
(cd offline && sha256sum go1.26.0.linux-amd64.tar.gz > go.SHA256SUMS)
(cd offline && sha256sum envoy-symbol-amd64.tar.gz supercronic-linux-amd64 \
  runtime-debs/*.deb > gateway.SHA256SUMS)
```

摘要用于检查传输完整性，自算摘要不代替来源验证。把整个 `offline/` 目录复制到企业源码目录 `/home/teaho/IdeaProjects/teaho-infra/higress/offline/`。只构建 Controller 时，仅需 Go 归档和 go.SHA256SUMS。

## ③ 准备源码与 Dockerfile

### 3.1 检查源码

在企业构建机执行，后续命令保持在同一 Bash 终端：

```bash
export HIGRESS_DIR=/home/teaho/IdeaProjects/teaho-infra/higress
export GUIDE_DIR=/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/private-build
cd "$HIGRESS_DIR"
git rev-parse HEAD
git status --short
git merge-base --is-ancestor 4deae1dd3b4cb2707273748985e55bef28e747d1 HEAD
git submodule status --recursive
```

官方 v2.2.5 提交为 `4deae1dd`；当前本机 HEAD 为 `e5e6ab1`，在该版本上恢复了 Go 依赖锁定。构建记录实际 HEAD，先审查本地修改，不能仅凭 v2.2.5 标签宣称输入完全一致。

子模块必须完整，状态每行以空格开头。若出现 `-`、`+`、`U`，先在能访问源码远端的环境执行 `git submodule update --init --recursive`，再传入完整源码。不能只使用不含子模块的 Source ZIP。

### 3.2 放入两个 Dockerfile

```bash
cp "$GUIDE_DIR/Dockerfile.controller" "$GUIDE_DIR/Dockerfile.controller.dockerignore" .
cp "$GUIDE_DIR/Dockerfile.gateway" "$GUIDE_DIR/Dockerfile.gateway.dockerignore" .
cp "$GUIDE_DIR/Makefile.private" "$GUIDE_DIR/prepare-source.sh" .
cp "$GUIDE_DIR/golang-filter-local-build.patch" .
(cd offline && sha256sum -c go.SHA256SUMS && sha256sum -c gateway.SHA256SUMS)
```

公司机器的 GUIDE_DIR 请改为收到本指引配套文件的实际目录。只构建 Controller 时，校验命令只执行 `sha256sum -c go.SHA256SUMS`。两个 Dockerfile 都自带编译、运行阶段：

```dockerfile
ARG BASE_IMAGE
ARG BUILD_TOOLS_IMAGE
FROM ${BUILD_TOOLS_IMAGE} AS build
# 安装离线 Go、准备源码，然后执行官方 make 单二进制目标

FROM ${BASE_IMAGE} AS base
# 运行基础，Gateway 在此离线安装 .deb

# 后续最终阶段从 base 开始，并 COPY --from=... 编译产物
```

- [Dockerfile.controller](../infra/private-build/Dockerfile.controller)：调用官方 Make 规则编译 higress、pilot-discovery；两个最终 target 为 controller、discovery。
- [Dockerfile.gateway](../infra/private-build/Dockerfile.gateway)：调用官方 Make 规则编译 pilot-agent，应用 Go filter 的 local-build 补丁；离线组装运行镜像。
- [Makefile.private](../infra/private-build/Makefile.private)：按顺序调用上述 Dockerfile，支持 HUB/TAG，不修改官方 Makefile。

专属 `.dockerignore` 必须一起复制，排除旧 external/、out 和产物，放行必要离线输入。[prepare-source.sh](../infra/private-build/prepare-source.sh) 只从子模块生成 external/ 和版本元数据，不编译；无需运行会拉取子模块和整理依赖的 `make prebuild`。

目录应包含：

```text
higress/
├── Dockerfile.controller / Dockerfile.controller.dockerignore
├── Dockerfile.gateway / Dockerfile.gateway.dockerignore
├── Makefile.private / prepare-source.sh
├── golang-filter-local-build.patch
├── offline/
│   ├── go1.26.0.linux-amd64.tar.gz / go.SHA256SUMS
│   ├── envoy-symbol-amd64.tar.gz
│   ├── supercronic-linux-amd64 / gateway.SHA256SUMS
│   └── runtime-debs/*.deb
├── go.mod / go.sum / cmd / pkg / hgctl / ...
├── istio/{api,client-go,pkg,istio}/...
├── envoy/go-control-plane/...
└── plugins/golang-filter/...
```

### 3.3 复用哪些官方规则，需要改哪些地方

Dockerfile 已改为中文注释，不再手写 controller/Pilot 的 `go build`。具体入口如下（`/out` 是构建容器目录）：

| 产物 | 实际编译入口 | 是否修改官方文件 |
| --- | --- | --- |
| higress | 根目录 `make ... /out/higress`，执行 `tools/hack/gobuild.sh` | 不修改；用参数覆盖版本包名 |
| pilot-discovery | `external/istio` 中 `make ... /out/pilot-discovery`，执行 `common/scripts/gobuild.sh` | 不修改 |
| pilot-agent | 同上，目标 `/out/pilot-agent` | 不修改 |
| golang-filter.so | `plugins/golang-filter` 中 `make local-build` | **容器内**为其 Makefile 增加一个目标 |

前三个目标统一传入 `BUILD_WITH_CONTAINER=0 BUILD_ALL=false TARGET_ARCH=amd64 TARGET_OS=linux TARGET_OUT=/out TARGET_OUT_LINUX=/out`。这样使用官方的单二进制规则及编译标签，不触发整个项目的 `prebuild` / `depend`、下载 Envoy、编译无关程序或嵌套启动 Docker。不要改为裸的 `make pilot-agent`，该快捷目标会进入全量 build。

**唯一文件补丁：** [golang-filter-local-build.patch](../infra/private-build/golang-filter-local-build.patch) 为官方 `plugins/golang-filter/Makefile` 增加 `local-build`。原 `build` 目标只调用 Docker，不适合放进 Dockerfile 的编译阶段。新增目标沿用官方 Go filter Dockerfile 的 amd64 命令：`CGO_ENABLED=1`、`CC=x86_64-linux-gnu-gcc`、`AS=x86_64-linux-gnu-as`、`-buildmode=c-shared`；通过 OUTPUT 指定产物路径。Dockerfile 自动 `git apply --check` 后应用到容器内源码副本，**无需在宿主 Higress 仓库手动修改或应用补丁**。补丁不匹配时会停止，应检查源码版本，不要强行忽略失败。

**controller 版本字段：** 当前根 Makefile 的 `VERSION_PACKAGE` 指向不存在的 `pkg/cmd/lversion`，实际代码是 `pkg/cmd/version`。Dockerfile 传入 `VERSION_PACKAGE=github.com/alibaba/higress/v2/pkg/cmd/version` 修正本次编译，不改官方 Makefile。Higress 二进制版本仍取官方 VERSION 文件的 `v2.2.5`；镜像标签为 `2.2.5-walmart`。`GIT_COMMIT` 和官方支持的 `BUILDINFO` 文件注入实际提交/构建版本，避免不带 .git 的构建上下文显示 unknown。

不执行官方 Dockerfile 中的 `go mod tidy`，保留只读依赖锁文件；需要更新依赖时，由你在相同工具链和代理下整理并审查。没有用另一个脚本悄悄替换官方 controller/Pilot 编译规则。

## ④ 编译镜像

### 4.1 配置 Harbor 引用

```bash
cd "$HIGRESS_DIR"
export BASE_IMAGE=harbor.qa.wal-mart.cn/base-image/higress-base:2023-07-20T20-50-43-amd64
export BUILD_TOOLS_IMAGE=harbor.qa.wal-mart.cn/base-image/higress-build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613
export HUB=harbor.qa.wal-mart.cn/nonprod-ai-gateway
export TAG=2.2.5-walmart
export GOPROXY=http://cno-repository.cn.wal-mart.com/repository/GoproxCn/
docker login harbor.qa.wal-mart.cn
```

BASE_IMAGE/BUILD_TOOLS_IMAGE 是步骤①实际导入的完整引用，生产流水线建议固定为 digest。HUB 是**输出仓库前缀**，不是基础镜像地址。

### 4.2 分服务构建

```bash
make -f Makefile.private docker-build-controller \
  HUB="$HUB" TAG="$TAG" BASE_IMAGE="$BASE_IMAGE" BUILD_TOOLS_IMAGE="$BUILD_TOOLS_IMAGE" GOPROXY="$GOPROXY"

make -f Makefile.private docker-build-gateway \
  HUB="$HUB" TAG="$TAG" BASE_IMAGE="$BASE_IMAGE" BUILD_TOOLS_IMAGE="$BUILD_TOOLS_IMAGE" GOPROXY="$GOPROXY"
```

也可以用一条命令顺序构建全部镜像（两种方式任选其一）：

```bash
make -f Makefile.private docker-build \
  HUB="$HUB" TAG=2.2.5-walmart \
  BASE_IMAGE="$BASE_IMAGE" BUILD_TOOLS_IMAGE="$BUILD_TOOLS_IMAGE" GOPROXY="$GOPROXY"
```

这个 `docker-build` 是配套 Makefile 的入口。原生 `make docker-build` 主要构建 controller，其他官方脚本仍默认引用阿里 build-tools；只改 HUB/TAG 不能消除所有外部依赖。外层入口执行 `docker build -f Dockerfile.controller/gateway`，容器内再执行上表中的官方源码编译规则；不在容器内启动 Docker，也不自动推送。

使用支持专属 dockerignore 的 BuildKit。公司 GOPROXY 需提供锁定模块和 fork 的 pseudo-version；构建不回退 GitHub、不自动下载 Go。若报需要更新 go.mod，应在同一工具链和公司代理下整理报错模块，审查并保存依赖后重建，不随意升级版本。若缺 `.deb`，回步骤②补齐；若 Go filter 有 GLIBC 错误，需调整编译环境与运行环境的兼容组合，不能只跳过检查。

Gateway 的构建自检会执行 Envoy/pilot-agent 版本检查、Go filter 的 `ldd` 依赖检查，以及 `supercronic -test /var/lib/istio/cron.txt`。当前离线 supercronic 不支持 `-version`，因此用它支持的 `-test` 验证程序和生成的定时任务配置。

### 4.3 检查并按需推送

构建成功后检查二进制版本，全部通过后再推送：

```bash
make -f Makefile.private docker-check HUB="$HUB" TAG="$TAG"
# 上面成功后再执行：
make -f Makefile.private docker-push HUB="$HUB" TAG="$TAG"
```

最终产物：

```text
harbor.qa.wal-mart.cn/nonprod-ai-gateway/controller:2.2.5-walmart
harbor.qa.wal-mart.cn/nonprod-ai-gateway/discovery:2.2.5-walmart
harbor.qa.wal-mart.cn/nonprod-ai-gateway/gateway:2.2.5-walmart
```

保存镜像 digest、源码/子模块 SHA 和离线文件摘要。版本检查与 ldd 仅确认基本可运行性；发布前仍需在测试集群验证 xDS、HTTP 路由、Go filter 及实际插件请求。本文止于构建，不执行集群更新。

### 4.4 本机实际构建记录（2026-10-19）

**结果：控制面两个镜像成功；Gateway 尚未通过。不能将这次验证视为三个镜像均可发布。**

使用源码 `e5e6ab188fba7e2e58bbf68e2704c4e94d8417fc` 的独立快照及对应子模块，在 `/home/teaho/.cache/higress-enterprise-build-3yl3tiz1/context` 构建。未修改原 Higress 仓库的已跟踪源码、未推送镜像、未部署或更新 minikube。

本地测试条件与企业环境的区别：基础镜像使用本机已有的同版官方 base/build-tools，并添加本地标签；公司 GOPROXY 的域名在本机无法解析，所以测试覆盖为 `https://goproxy.cn`。没有验证企业 Harbor 的证书、权限或公司代理是否包含全部依赖。`registry.local/higress` 只是本次本地镜像标签前缀，没有向它推送。

准备好步骤②的离线文件并放入快照后，实际构建命令为：

```bash
cd /home/teaho/.cache/higress-enterprise-build-3yl3tiz1/context
export BASE_IMAGE=higress/base:2023-07-20T20-50-43-amd64
export BUILD_TOOLS_IMAGE=higress/build-tools:release-1.19-ef344298e65eeb2d9e2d07b87eb4e715c2def613
export HUB=registry.local/higress
export TAG=2.2.5-walmart
export GOPROXY=https://goproxy.cn
export SOURCE_REVISION=e5e6ab188fba7e2e58bbf68e2704c4e94d8417fc

# 成功，退出码 0，输出 controller 和 discovery。
make -f Makefile.private docker-build-controller \
  HUB="$HUB" TAG="$TAG" BASE_IMAGE="$BASE_IMAGE" \
  BUILD_TOOLS_IMAGE="$BUILD_TOOLS_IMAGE" GOPROXY="$GOPROXY" \
  SOURCE_REVISION="$SOURCE_REVISION"

# 已执行，但未成功输出最终 gateway 镜像，错误见下文。
make -f Makefile.private docker-build-gateway \
  HUB="$HUB" TAG="$TAG" BASE_IMAGE="$BASE_IMAGE" \
  BUILD_TOOLS_IMAGE="$BUILD_TOOLS_IMAGE" GOPROXY="$GOPROXY" \
  SOURCE_REVISION="$SOURCE_REVISION"

# 已通过：使用默认 ENTRYPOINT、禁用网络检查两个镜像。
docker run --rm --network none "$HUB/controller:$TAG" version
docker run --rm --network none "$HUB/discovery:$TAG" version
```

| 本地镜像 | Image ID 前缀 | 大小（未压缩，十进制） | 验证结果 |
| --- | --- | --- | --- |
| `registry.local/higress/controller:2.2.5-walmart` | `c44c85208308` | 216 MB | 官方 Make 编译、镜像构建、默认入口 `version` 均通过 |
| `registry.local/higress/discovery:2.2.5-walmart` | `cb2cf2ebaae0` | 210 MB | 官方 Make 编译、镜像构建、默认入口 `version` 均通过 |
| `registry.local/higress/gateway:2.2.5-walmart` | 未生成 | — | 未通过最终构建，未执行 HTTP/xDS 验证 |

controller 输出 `HIGRESS_VERSION: v2.2.5` 和上述源码 SHA；discovery 输出 `2.2.5-walmart`、相同源码 SHA、`go1.26.0`。不带 `.git` 的快照会使官方 Make 的部分 Git 查询打印提示，但已通过参数和 BUILDINFO 注入实际版本，成功目标的退出码为 0。

实际发现并修正了三处问题，正文和配套 Dockerfile 已同步：

1. apt 缓存的 `partial/` 权限使 Docker 无法读取构建上下文：改为仅复制 `.deb`，缓存目录移出上下文。
2. 旧 apt 的 `--no-download` 安装本地包报内部路径错误：改用 `dpkg -i`，已在禁用网络的临时 base 容器中安装并检查成功。
3. 官方 supercronic 不支持 `-version`：改为 `-test` 验证 crontab，已单独运行通过。

**剩余阻塞：Go filter 的编译器内部错误。** pilot-agent 已编译通过；Go filter 首轮也曾编译成功，但该轮在上述 supercronic 自检处停止。修正后重建，先后出现不同错误：

```text
Go 1.26.0 / milvus-sdk-go/v2/entity:
  internal compiler error: values has no location
GCC 11 / go-sqlite3 / vartrack:
  internal compiler error: in val_bind, at var-tracking.c:2504
试用 Go 1.26.9、CGO_CFLAGS="-O2 -g0" 后的链接阶段:
  runtime.init.5: invalid relocation runtime.funcMaxSPDelta: 262198+4 not in [0,197)
```

工具链升级尝试仍未通过，因此已撤回，配套文件保持 Go 1.26.0 和原 C 编译参数；没有通过关闭检查或反复重试掩盖问题。不同失败阶段的根因尚未确定，不能断言是 Higress 业务代码错误，也没有证据确认硬件故障。后续应在保留这些日志的前提下，用独立构建机对照验证工具链/主机环境，再继续 Gateway 运行验证。

完整日志与输入摘要位于 `/home/teaho/.cache/higress-enterprise-build-3yl3tiz1`：`logs/controller-build-1.log`、`logs/gateway-build-3.log` 至 `logs/gateway-build-6.log`、`logs/controller-entrypoint.log`、`logs/discovery-entrypoint.log`、`logs/images.json`、`inputs.json`。本次没有完成 Envoy 加载 Go filter、HTTP 请求、xDS 或 Kubernetes 部署验证。
