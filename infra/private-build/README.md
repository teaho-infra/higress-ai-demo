# Higress 企业内网源码镜像构建

> **历史方案，已由源码仓库中的新版替代。** 请使用 [Higress 企业构建指引](https://github.com/teaho-infra/higress/blob/ft/v2.2.5-teaho/docs/walmart/README.md) 和 [本地验证记录](https://github.com/teaho-infra/higress/blob/ft/v2.2.5-teaho/docs/walmart/verification.md)。新版独立使用 Go 1.23/bullseye 编译 Go filter，已于 2026-10-19 完成 higress-core、discovery、higress-gateway 三个镜像构建及 Envoy/Go filter/HTTP 200 验证。下文和本目录 Dockerfile 保留旧方案与失败记录，不作为当前执行入口。

按四步执行：[完整分步指引](../../plan/higress-2.2.5-enterprise-source-build-codex.md)。

- [Dockerfile.controller](Dockerfile.controller)：编译并打包 controller、discovery 两个控制面镜像。
- [Dockerfile.gateway](Dockerfile.gateway)：编译 pilot-agent、Go filter，并与离线 Envoy 组装 Gateway。
- [Makefile.private](Makefile.private)：外层镜像构建入口；容器内复用官方 Make 编译规则。
- [prepare-source.sh](prepare-source.sh)：准备 external/ 和版本信息，不编译。
- [Go filter 补丁](golang-filter-local-build.patch)：仅在容器内增加本机编译目标。

源码上下文：`/home/teaho/IdeaProjects/teaho-infra/higress`。每个 Dockerfile 必须连同同名 `.dockerignore` 一起使用。

基础镜像为从官方仓库导入 Harbor 的 **base + build-tools**，不是预先构建好的业务镜像。Envoy 使用官方预编译文件。2026-10-19 本机实测：controller、discovery 已构建成功并通过启动检查；gateway 在 Go filter 编译阶段遇到未解决的编译器内部错误，不能视为已验证可用。详情见指引 4.4。
