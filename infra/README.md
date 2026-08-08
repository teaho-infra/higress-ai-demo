# higress-ai-demo — infrastructure

## 启动

```bash
cp .env.example .env   # 填上真实 OPENAI_API_KEY 等
docker compose up -d
docker compose ps       # 验证所有服务 healthy
```

## 服务

| 服务 | 镜像 | 端口 | 容器名 |
|---|---|---|---|
| Nacos | `nacos/nacos-server:v2.5.3` | 8848/9848/9849 | `nacos-standalone` |
| Higress | `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:latest` | 8001/8080/8443 | `higress-ai` |

## 常用命令

```bash
# 启停
docker compose up -d
docker compose stop
docker compose down        # 停 + 删容器,保留数据卷
docker compose down -v     # 停 + 删容器 + 删数据卷

# 看日志
docker compose logs -f nacos
docker compose logs -f higress

# 进容器
docker compose exec nacos bash
docker compose exec higress sh
```

## 验证

```bash
# Nacos
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8848/nacos/
# Higress Console
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/
# Higress Gateway
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
```

## HiMarket 部署备忘(留到 Task 10)

```bash
git clone https://github.com/higress-group/himarket.git
cd himarket/deploy/docker
./install.sh -n           # 非交互
# 等 8 容器 healthy
```

| HiMarket 服务 | 端口 | 凭证 |
|---|---|---|
| Portal | 5173 | — |
| Admin | 5174 | admin/admin |
| Server | 8081 | — |
| HiMarket 内 Higress Gateway | **8082** | — |
| HiMarket 内 Higress Console | 8001 | admin/admin |
| HiMarket 内 Nacos | 8848 | nacos/nacos |
