# Nacos 2.5.3 + Higress 2.2.3 - 本地部署

仅本机,无鉴权。

## Nacos
- 镜像: `nacos/nacos-server:v2.5.3`
- 模式: standalone + Derby
- 端口: 8848 (http) + 9848 (gRPC server) + 9849 (gRPC client RPC)
- 数据卷: ./data/nacos
- 容器名: nacos-standalone

## Higress
- 镜像: higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:latest
- 端口: 8001 (Console) + 8082 (Gateway HTTP, 容器内 8080 — 本机 8080 被占) + 8443 (Gateway HTTPS)
- 数据卷: ./data/higress
- 容器名: higress-ai
