
# higress notes


## 下载转换插件

oras backup \
  --output key-auth-2.0.0.tar \
  higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/key-auth:2.0.0

oras backup \
  --output ai-proxy-2.0.1.tar \
  higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/ai-proxy:2.0.1


oras backup \
  --output ai-agent-2.0.1.tar \
  higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/ai-agent:2.0.1

oras backup \
  --output ai-statistics-2.0.1.tar \
  higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/ai-statistics:2.0.1



你改了哪些地方使得higress-gateway从私有源拉取插件？

让 Higress Gateway 从私有源拉取 Wasm 插件，涉及四处配置：

1. 部署了集群内的 [私有 OCI Registry](/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/codex-private-wasm-registry.yaml:14)，使用 PVC 存储和 Basic Auth，并把官方插件镜像同步进去。
2. 在 [Gateway Helm 配置](/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/higress-values.yaml:11)中，将该 Registry 加入 `WASM_INSECURE_REGISTRIES`。因为本机实验的 Registry 使用 HTTP，Gateway 需要允许访问它。
3. 在每个插件的 `WasmPlugin` 配置中，把 `spec.url` 设为私有库的 `oci://...`   地址，并设置 `spec.imagePullSecret: codex-private-wasm-pull`；[官方 key-auth 示例](/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/codex-official-key-auth.yaml:43)展示了这两个字段。这个 Secret 用于 **Wasm 镜像拉取**，不是 Gateway Pod 的 `imagePullSecrets`。
4. 在 [Console Helm 配置](/home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/infra/minikube/console-values.yaml:12)中设置私有 Registry、`plugins` 命名空间和拉取 Secret，让 Console **新创建的内置插件配置**自动写入上述地址和 Secret。

你刚开启的 `ai-agent` CR 已包含私有库 URL 和拉取 Secret；Registry 日志也确认 Gateway 成功拉取了镜像。它当前加载失败是 `apiProvider` 配置错误，与私有源连接或认证无关。



{
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {
        "name": "harbor-wasm-pull",
        "namespace": "qa-ai-gateway"
    },
    "type": "kubernetes.io/dockerconfigjson",
    "data": {
        ".dockerconfigjson": "tset"idSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
    }
}

## demo request

~~~
curl --noproxy '*' -sv   http://192.168.67.2/v1/chat/completions   -H 'Content-Type: application/json'   -H 'Host: higress-gateway.qa.wal-mart.cn'   -d '{
    "model": "MiniMax-M3",
    "messages": [
      {"role": "user", "content": "你在用什么模型"}
    ]
  }'
~~~


## 排除问题


### 排查ai-proxy插件的问题

1. 拉取配置
~~~
DUMP=$(mktemp /tmp/higress-config.XXXXXX.json)

kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS http://127.0.0.1:15000/config_dump > "$DUMP"

~~~
config_dump 包含 Envoy 当前生效、等待生效以及被拒绝的配置。


2. 检查listener，看active state的listener
~~~
jq '
  .configs[]
  | .dynamic_listeners[]?
  | select(.active_state != null)
  | {
      listener: .name,
      updated: .active_state.last_updated,
      ai_proxy_filters: [
        .active_state.listener
        | ..
        | objects
        | .http_filters[]?
        | select(.name | contains("ai-proxy"))
        | .name
      ]
    }
' "$DUMP"

~~~

成功时应该看到类似：
{
  "listener": "0.0.0.0_80",
  "updated": "...",
  "ai_proxy_filters": [
    "extensions.istio.io/wasmplugin/higress-system.ai-proxy.internal",
    "extensions.istio.io/wasmplugin/higress-system.codex-ai-proxy"
  ]
}

3. 检查 ECDS 中是否存在已加载的插件配置

Listener 引用了插件，还要有对应的动态扩展配置：
jq '
  .configs[]
  | .ecds_filters[]?
  | .ecds_filter
  | select(.name | contains("ai-proxy"))
  | {
      resource: .name,
      plugin: .typed_config.config.name
    }
' "$DUMP"


4. 检查被拒绝的 Listener，以及拒绝原因
~~~
jq '
  .configs[]
  | .dynamic_listeners[]?
  | select(.error_state != null)
  | {
      listener: .name,
      failed_at: .error_state.last_update_attempt,
      reason: .error_state.details,
      rejected_ai_proxy_filters: [
        .error_state.failed_configuration
        | ..
        | objects
        | .http_filters[]?
        | select(.name | contains("ai-proxy"))
        | .name
      ]
    }
' "$DUMP"
~~~
类似的失败内容就是：
reason:
  Unable to create Wasm plugin higress-system.ai-agent-2.0.1

rejected_ai_proxy_filters:
  extensions.istio.io/wasmplugin/higress-system.ai-proxy.internal

5. 5. 用统计指标和日志交叉确认
查看 AI Proxy 的更新指标：
~~~~
kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS http://127.0.0.1:15000/stats |
grep -E 'ai-proxy\.internal.*(update_success|update_rejected|config_fail):'
~~~~
查看近期加载失败日志：
~~~~
kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway --since=30m |
grep -E 'Unable to create Wasm plugin|failed to load|Error adding/updating listener|config.*rejected'
~~~~

以上确认的是加载状态。要确认某一次请求执行了 AI Proxy，还要核对它的域名／路由／服务匹配规则，并结合该请求的插件日志判断。


### 通过日志路由、插件、上游的问题

如何区分这三种情况，查gateway日志

| 情况 | 主要证据 | 含义 |
|---|---|---|
| Higress 没匹配到路由 | `response_code_details=route_not_found`，常见 `response_flags=NR`，无上游地址 | 在入口路由阶段失败 |
| 插件处理失败或主动拒绝 | `response_code_details` 出现 `via_wasm::...`，或插件日志出现解析、执行错误 | 根据插件名和错误定位；插件加载失败还要查 ECDS/Listener |
| 上游返回错误 | `response_code_details=via_upstream`，有 `upstream_cluster` 和 `upstream_host` | 请求已发往上游，由上游返回状态码 |
| 连接上游失败 | `UF`、`UT` 等标志，连接失败或超时详情 | 检查网络、TLS、端口、超时 |


查日志

~~~
kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway \
  --since=1m -f
~~~

route_name: ai-route-minimax-test.internal
upstream_cluster: outbound|443||llm-minimax.internal.dns
upstream_host: 101.132.45.96:443
response_code: 404
response_code_details: via_upstream



### 查看单次请求访问日志


~~~
构造rquestid 去请求
RID=$(cat /proc/sys/kernel/random/uuid)
echo "$RID"

curl --noproxy '*' -sv \
  http://192.168.67.2/v1/chat/completions \
  -H 'Host: higress-gateway.qa.wal-mart.cn' \
  -H 'Content-Type: application/json' \
  -H "X-Request-ID: $RID" \
  -d '{"model":"minimax-m3","messages":[{"role":"user","content":"Hello!"}]}'

 
// 查日志

kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway --since=5m |
jq -R --arg id "$RID" '
  fromjson?
  | select(.request_id == $id)
  | {
      request_id, route_name, method, authority, path,
      response_code, response_code_details, response_flags,
      upstream_cluster, upstream_host,
      upstream_service_time, upstream_transport_failure_reason
    }'


kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway --since=5m |
jq -R  '
  fromjson?
  | select(.method == "POST")
  | {
      request_id, route_name, method, authority, path,
      response_code, response_code_details, response_flags,
      upstream_cluster, upstream_host,
      upstream_service_time, upstream_transport_failure_reason
    }
'
~~~


### 查请求是否通过ai-proxy的情况


#### 临时开关debug

本机可以临时打开 Envoy 和 Wasm 调试日志。我刚查过，本机这三个日志级别目前都是 warning：
kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS -X POST \
  'http://127.0.0.1:15000/logging?paths=http:debug,router:trace,wasm:debug'


关闭debug

kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS -X POST \
  'http://127.0.0.1:15000/logging?paths=http:warning,router:warning,wasm:warning' 


#### 查看日志

kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway \
  --since=1m -f
