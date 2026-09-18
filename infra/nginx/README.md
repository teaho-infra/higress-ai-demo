# nginx + Tailscale Funnel 暴露 Higress Console

本机用户级 nginx（`~/.local/nginx`，监听 `:8443`）经 Tailscale Funnel 公网暴露。
Higress Console 挂在 `/higress/` 前缀，回源 minikube gateway `127.0.0.1:18080`。

## 访问地址

- 公网：`https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/`
- 本地：`http://127.0.0.1:8443/higress/`
- 直连 gateway（免 host）：`http://127.0.0.1:18080/`

## 拓扑

```
公网 --> Tailscale Funnel :443 --> nginx :8443 --> /higress/ --> minikube gateway :18080 --> higress-console svc
```

## 关键文件

| 文件 | 说明 |
|---|---|
| `higress-locations.conf` | 本仓库备份；nginx 侧 `/higress/` 前缀 location + sub_filter |
| `~/.local/nginx/conf/nginx.conf` | 主配置，include 上述文件（第 151-152 行） |
| `~/.local/nginx/conf/wso2-locations.conf` | WSO2 已有配置（未改） |

## 为什么需要 sub_filter

Higress console 是无 basePath 的 ice SPA：静态资源（`/css/`、`/js/`）与 API（`/api/`）
硬编码在**根路径**下。直接挂 `/higress/` 前缀会让资源 404。

解法：`location /higress/` 用 `proxy_pass http://127.0.0.1:18080/`（带 URI 剥前缀），
并对响应做 `sub_filter`，把 `/css/`、`/js/`、`/api/`、`/higress.jpg` 重写为
`/higress/` 前缀。sub_filter 类型覆盖 HTML + JS。

## 验证

```bash
# 公网
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/          # 200
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/css/main-*.css  # 200
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/api/         # 200

# 确认 HTML 资源已重写为 /higress/ 前缀(而非根路径)
curl -s https://leonbook5-jiguang-series.tailb1426a.ts.net/higress/ | grep -o 'href="/higress/css/[^"]*"' | head

# 未破坏其他服务
curl -o /dev/null -w '%{http_code}\n' https://leonbook5-jiguang-series.tailb1426a.ts.net/    # multica 200
```

## reload

```bash
export PATH=$HOME/bin:$PATH
nginx -s reload -c /home/leonbook5/.local/nginx/conf/nginx.conf
```