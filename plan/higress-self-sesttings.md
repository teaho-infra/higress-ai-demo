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



curl --noproxy '*' -sv   http://192.168.67.2/v1/chat/completions   -H 'Content-Type: application/json'   -H 'Host: higress-gateway.qa.wal-mart.cn'   -d '{
    "model": "MiniMax-M3",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
