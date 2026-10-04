# Minikube：手写 Higress Wasm 插件、打包、Console 添加与验证

本文是供你逐步执行的教程与计划，创建于 2026-10-04。**编写本文时没有执行下面的命令，没有编译、推送或部署插件；所有结果均为预期验收标准，不是本次实测结果。**

沿用本项目已有的 Minikube `higress-dev`、namespace `higress-system`、Higress v2.2.4 和带认证的本机 OCI Registry。本文不操作其他集群。每一步成功后再继续；出现错误时停在该步检查。

## 1. 要做什么

编写 `leon-hello`：

- 仅处理配置中指定的测试域名 `wasm-demo.local`。
- 对 `/hello` 直接返回问候语，并附加 `x-leon-wasm: 0.1.0` 响应头。
- 在 Console 把 `blocked` 改成 `true` 后，同一个请求变为 `403`。
- 对其他路径、其他域名放行，不读取或记录请求正文与认证信息。

这是一个“网关本地应答”插件：命中 `/hello` 时不请求后端。测试后端用于证明路由原本可用，并验证其他路径能继续转发。

整体顺序：准备集群 → 编写 Go 插件 → 编译 Wasm → 打包兼容镜像 → 推送私有 Registry → 部署测试路由 → Console 创建并启用 → 检查 Envoy 和请求结果。

将来由你执行命令创建的目录：

```text
wasm/leon-hello/
├── go.mod
├── go.sum                     # go mod tidy 生成
├── main.go
├── plugin.wasm                # 编译生成
├── Dockerfile
├── .dockerignore
├── backend.yaml               # Deployment + Service + Ingress
└── wasmplugin.yaml            # 可选：直接 CR 部署，勿与 Console 重复创建
```

## 2. 确认工具和基础服务

在本机终端执行：

```bash
kubectl config get-contexts
minikube -p higress-dev status
docker version
docker buildx version
python3 --version
jq --version
```

如果 Minikube 已停止，执行 `minikube -p higress-dev start`。若缺少 jq，Ubuntu 可执行 `sudo apt update` 和 `sudo apt install -y jq`。需要 Docker Buildx 支持 Docker 镜像导出及 gzip 压缩选项。

先确认已有资源；如返回 NotFound，请先按 [已有集群指南](minikube-source-build-cluster-codex.md)恢复基础环境，不要把本教程当作全新集群安装器：

```bash
kubectl --context higress-dev -n higress-system get deployment \
  higress-controller higress-gateway higress-console codex-private-wasm-registry
kubectl --context higress-dev -n higress-system get secret codex-private-wasm-pull \
  -o jsonpath='{.type}{"\n"}'
```

Secret 类型必须为 `kubernetes.io/dockerconfigjson`。

如果三个 Higress 组件此前被缩容到 0，逐个启动并等待：

```bash
for component in higress-controller higress-gateway higress-console; do
  kubectl --context higress-dev -n higress-system scale \
    deployment/"$component" --replicas=1 || break
  kubectl --context higress-dev -n higress-system rollout status \
    deployment/"$component" --timeout=180s || break
done

kubectl --context higress-dev -n higress-system get pods
```

检查 Gateway 是否允许现有实验 HTTP Registry：

```bash
kubectl --context higress-dev -n higress-system get deployment higress-gateway -o json |
jq '.spec.template.spec.containers[]
    | select(.name == "higress-gateway")
    | .env[]?
    | select(.name == "WASM_INSECURE_REGISTRIES")'
```

值应包含 `codex-private-wasm-registry.higress-system.svc.cluster.local:5000`。本项目的 `infra/minikube/higress-values.yaml` 已配置该地址。如果实际配置缺失，应合并到原有逗号分隔列表并通过原 Helm 配置更新，保留其他仓库地址。

## 3. 创建目录和依赖文件

```bash
cd /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo
mkdir -p wasm/leon-hello
cd wasm/leon-hello

cat > go.mod <<'EOF'
module example.com/leon-hello

go 1.24.1

toolchain go1.24.4

require (
    github.com/higress-group/proxy-wasm-go-sdk v0.0.0-20250822030947-8345453fddd0
    github.com/higress-group/wasm-go v1.0.2-0.20250821081215-b573359becf8
    github.com/tidwall/gjson v1.18.0
)
EOF
```

依赖版本取自 Higress v2.2.4 的 request-block 示例。这里使用标准 Go 1.24 的 Wasm 编译方式，不混用旧 TinyGo 教程。SDK 的 `wrapper` 负责解释 Higress 下发的规则和配置；直接使用底层 SDK 时不要假设它会自动识别 Higress 的匹配规则。

## 4. 写一个完整插件

```bash
cat > main.go <<'EOF'
package main

import (
    "strings"

    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm"
    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
    "github.com/higress-group/wasm-go/pkg/log"
    "github.com/higress-group/wasm-go/pkg/wrapper"
    "github.com/tidwall/gjson"
)

type Config struct {
    allowedHost string
    message     string
    blocked     bool
}

func main() {}

func init() {
    wrapper.SetCtx(
        "leon-hello",
        wrapper.ParseConfigBy(parseConfig),
        wrapper.ProcessRequestHeadersBy(onRequestHeaders),
    )
}

func parseConfig(value gjson.Result, config *Config, logger log.Log) error {
    config.allowedHost = value.Get("allowed_host").String()
    if config.allowedHost == "" {
        config.allowedHost = "wasm-demo.local"
    }
    config.message = value.Get("message").String()
    if config.message == "" {
        config.message = "Hello from leon-hello!"
    }
    config.blocked = value.Get("blocked").Bool()
    return nil
}

func onRequestHeaders(ctx wrapper.HttpContext, config Config, logger log.Log) types.Action {
    ctx.DontReadRequestBody()

    host, err := proxywasm.GetHttpRequestHeader(":authority")
    if err != nil {
        return types.ActionContinue
    }
    // 本示例使用 DNS 域名；去掉客户端可能附带的端口。
    host = strings.SplitN(host, ":", 2)[0]
    if !strings.EqualFold(host, config.allowedHost) {
        return types.ActionContinue
    }

    path, err := proxywasm.GetHttpRequestHeader(":path")
    if err != nil || strings.SplitN(path, "?", 2)[0] != "/hello" {
        return types.ActionContinue
    }

    code := uint32(200)
    detail := "leon-hello.reply"
    body := config.message + "\n"
    if config.blocked {
        code = 403
        detail = "leon-hello.blocked"
        body = "Blocked by leon-hello\n"
    }

    headers := [][2]string{
        {"content-type", "text/plain; charset=utf-8"},
        {"x-leon-wasm", "0.1.0"},
    }
    if err := proxywasm.SendHttpResponseWithDetail(code, detail, headers, []byte(body), -1); err != nil {
        logger.Errorf("local response failed: %v", err)
    }
    return types.ActionContinue
}
EOF
```

关键点：`init()` 注册回调；`parseConfig` 读取 Console 配置；请求头回调按域名和路径决定是否应答。`SendHttpResponseWithDetail` 的 detail 可以帮助你在访问日志中区分插件返回和上游返回。

即使在 Console 全局启用，本示例也只处理 `wasm-demo.local/hello`；其他请求继续走原有过滤器和路由。后续开发真实插件时仍建议通过 Console 的域名/路由范围控制应用范围。

## 5. 编译 plugin.wasm

推荐用固定 Go 容器编译，这样不需要修改宿主机 Go 版本。保持当前目录为 `wasm/leon-hello`：

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e GOCACHE=/tmp/go-build \
  -e GOPATH=/tmp/go \
  -v "$PWD:/src" -w /src \
  golang:1.24.4 \
  sh -c 'go mod tidy && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm .'
```

首次运行需要下载构建镜像及 Go 依赖；如果网络失败，先解决下载，不要继续打包旧产物。成功后应出现 `go.sum` 和 `plugin.wasm`。

如果宿主机已经有兼容的 Go 1.24.4，也可以用下面两条替代容器构建，不必执行两遍：

```bash
go mod tidy
GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm .
```

检查 Wasm 文件头：

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('plugin.wasm')
with p.open('rb') as f:
    assert f.read(4) == b'\x00asm', '不是有效的 Wasm 文件头'
print('Wasm header OK; bytes =', p.stat().st_size)
PY
```

文件头检查只能证明产物是 Wasm；是否能被 Higress 加载还要通过后面的 ECDS 和请求测试验证。

## 6. 打包为 Higress 支持的镜像

Wasm 插件镜像用于存储模块，不作为 Pod 运行。因此不需要 Nginx 或可执行 ENTRYPOINT。本示例选择兼容容器镜像格式：gzip 压缩层中包含根目录的 `plugin.wasm`。

```bash
cat > Dockerfile <<'EOF'
FROM scratch
COPY plugin.wasm /plugin.wasm
EOF

cat > .dockerignore <<'EOF'
*
!Dockerfile
!plugin.wasm
EOF

docker buildx build \
  --platform linux/amd64 \
  --provenance=false --sbom=false \
  --output type=docker,dest=leon-hello-image.tar,compression=gzip,force-compression=true,oci-mediatypes=false \
  -t localhost:15006/plugins/leon-hello:0.1.0 .

docker load -i leon-hello-image.tar
```

这里生成的是 Docker 镜像归档，下一步由 Docker 加载并推送。不要用 `oras push image.tar` 把整个镜像归档当成一个任意文件上传，也不要仅修改 Manifest 的 media type。

先前的 `application/vnd.oci.image.layer.v1.tar` 错误来自镜像内部未压缩层；把外层归档压成 tar.gz 无法修复它。此处显式选择 gzip 和 Docker media type，并关闭附加 provenance/SBOM，减少单模块教学镜像的格式差异。

## 7. 推送到已存在的私有 Registry

两个地址的用途不同：

| 地址 | 使用者 |
|---|---|
| `localhost:15006` | 宿主机 Docker，通过 kubectl port-forward 推送 |
| `codex-private-wasm-registry.higress-system.svc.cluster.local:5000` | Gateway，通过集群网络拉取 |

### 7.1 终端 A：保持 Registry 转发运行

```bash
kubectl --context higress-dev -n higress-system port-forward \
  service/codex-private-wasm-registry 15006:5000 --address 127.0.0.1
```

此终端暂时不要关闭。

### 7.2 终端 B：复用现有凭据，不输出密码

```bash
cd /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/wasm/leon-hello
export WASM_DOCKER_CONFIG=$(mktemp -d /tmp/leon-hello-auth.XXXXXX)

python3 - <<'PY'
import base64, json, os, subprocess
from pathlib import Path

raw = subprocess.check_output([
    'kubectl', '--context', 'higress-dev', '-n', 'higress-system',
    'get', 'secret', 'codex-private-wasm-pull', '-o', 'json'
])
secret = json.loads(raw)
assert secret['type'] == 'kubernetes.io/dockerconfigjson'
data = json.loads(base64.b64decode(secret['data']['.dockerconfigjson']))
host = 'codex-private-wasm-registry.higress-system.svc.cluster.local:5000'
config = Path(os.environ['WASM_DOCKER_CONFIG']) / 'config.json'
config.write_text(json.dumps({'auths': {'localhost:15006': data['auths'][host]}}))
config.chmod(0o600)
print('Temporary push credentials prepared')
PY

docker --config "$WASM_DOCKER_CONFIG" push \
  localhost:15006/plugins/leon-hello:0.1.0
```

此处依据原实验 Registry 的同一账号具有推送和拉取能力。若以后迁移到 Harbor，应分别配置具有 push 和 pull 权限的账号。

### 7.3 检查 Registry 中的 Manifest

下面只输出镜像格式和层摘要，不输出认证信息：

```bash
python3 - <<'PY'
import json, os, urllib.request
from pathlib import Path

config = json.loads((Path(os.environ['WASM_DOCKER_CONFIG']) / 'config.json').read_text())
auth = config['auths']['localhost:15006']['auth']
req = urllib.request.Request(
    'http://127.0.0.1:15006/v2/plugins/leon-hello/manifests/0.1.0',
    headers={
        'Authorization': 'Basic ' + auth,
        'Accept': 'application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'
    }
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(req, timeout=15) as response:
    manifest = json.load(response)
print(json.dumps({
    'mediaType': manifest.get('mediaType'),
    'layers': manifest.get('layers')
}, indent=2))
layers = manifest.get('layers', [])
assert len(layers) == 1, '本教学镜像预期只有一个 COPY 层'
assert layers[0]['mediaType'] in (
    'application/vnd.docker.image.rootfs.diff.tar.gzip',
    'application/vnd.oci.image.layer.v1.tar+gzip'
), '层必须是 Higress 支持的 gzip tar 格式'
PY
```

检查通过后，在终端 A 按 Ctrl+C 停止转发。Gateway 拉取使用集群 Service，不依赖它。终端 B 清理临时推送凭据：

```bash
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ['WASM_DOCKER_CONFIG'])
(root / 'config.json').unlink()
root.rmdir()
PY
unset WASM_DOCKER_CONFIG
```

## 8. 部署测试后端和路由

在插件目录创建文件：

```bash
cat > backend.yaml <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: leon-hello-backend
  namespace: higress-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: leon-hello-backend
  template:
    metadata:
      labels:
        app: leon-hello-backend
    spec:
      containers:
        - name: echo
          image: hashicorp/http-echo:1.0.0
          args: ["-listen=:5678", "-text=hello-from-backend"]
          ports:
            - containerPort: 5678
          readinessProbe:
            httpGet:
              path: /
              port: 5678
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              memory: 64Mi
---
apiVersion: v1
kind: Service
metadata:
  name: leon-hello-backend
  namespace: higress-system
spec:
  selector:
    app: leon-hello-backend
  ports:
    - port: 5678
      targetPort: 5678
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: leon-hello-route
  namespace: higress-system
spec:
  ingressClassName: higress
  rules:
    - host: wasm-demo.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: leon-hello-backend
                port:
                  number: 5678
EOF

kubectl --context higress-dev apply -f backend.yaml
kubectl --context higress-dev -n higress-system rollout status \
  deployment/leon-hello-backend --timeout=180s
```

如果后端镜像下载失败，先处理 ImagePullBackOff，不要把后端未就绪误判为插件错误。

用专用端口转发测试，避免依赖历史 NodePort、代理或 hosts 配置。在终端 C 保持运行：

```bash
kubectl --context higress-dev -n higress-system port-forward \
  service/higress-gateway 18081:80 --address 127.0.0.1
```

终端 B 测试基线，此时还没有启用新插件：

```bash
curl --noproxy '*' -i -H 'Host: wasm-demo.local' \
  http://127.0.0.1:18081/hello
```

预期 HTTP 200、正文 `hello-from-backend`，没有 `x-leon-wasm`。如果已经有全局鉴权等插件要求凭据，需要先为测试域名配置合适的规则；不要直接关闭业务插件。

## 9. 从 Console 创建、配置和启用

### 9.1 打开 Console

在终端 D 保持运行：

```bash
kubectl --context higress-dev -n higress-system port-forward \
  service/higress-console 18082:8080 --address 127.0.0.1
```

浏览器打开 `http://127.0.0.1:18082/`，用原来的 Console 账号登录。这个入口直接访问 Console，不需要 Host 为 `console.higress.io`，也不依赖 Gateway 路由。

### 9.2 创建自定义插件卡片

在“插件市场 / Wasm 插件”页面点击“创建”，选择自定义插件。具体菜单文字可能随 Console 版本变化。

| 字段 | 填写内容 |
|---|---|
| 名称 | `leon-hello` |
| 展示名称（如有） | `Leon Hello` |
| 镜像地址 | `oci://codex-private-wasm-registry.higress-system.svc.cluster.local:5000/plugins/leon-hello:0.1.0` |
| 镜像拉取 Secret（如有） | `codex-private-wasm-pull` |
| 执行阶段（如有） | 默认阶段 / UNSPECIFIED_PHASE |
| 优先级（如有） | `100` |
| 描述 | `教学插件：指定域名和路径本地应答` |

镜像地址里不能填宿主机的 `localhost:15006`。在 Gateway 容器里 localhost 指向 Gateway 自己。

若页面要求 JSON Schema，可填写：

```yaml
type: object
properties:
  allowed_host:
    type: string
    default: wasm-demo.local
  message:
    type: string
    default: Hello from leon-hello!
  blocked:
    type: boolean
    default: false
```

若当前版本只提供 YAML 配置编辑器，直接在下一步填写配置即可，不必额外添加 Schema。

### 9.3 配置并启用

创建卡片后点击“配置”，填写：

```yaml
allowed_host: wasm-demo.local
message: Hello from Console!
blocked: false
```

本教程可以在卡片中全局启用这一个插件，因为代码有明确的域名和 `/hello` 限制；如果当前页面支持选择域名范围，优先只绑定 `wasm-demo.local` 并使用同样配置。不要把它绑定到现有 MiniMax 路由。

保存配置并打开启用开关。**只创建卡片，不代表插件已启用。**

### 9.4 确认 Console 生成的资源与 Secret

```bash
kubectl --context higress-dev -n higress-system get wasmplugin \
  -o custom-columns=NAME:.metadata.name,URL:.spec.url,SECRET:.spec.imagePullSecret
```

找到 URL 含 `plugins/leon-hello:0.1.0` 的那一行。Console 生成的资源名可能附带版本号，以实际输出为准。下面变量要替换成真实 NAME：

```bash
PLUGIN_CR=替换为上一步实际NAME

kubectl --context higress-dev -n higress-system get wasmplugin "$PLUGIN_CR" -o json |
jq '{name:.metadata.name, url:.spec.url, imagePullSecret:.spec.imagePullSecret,
     defaultConfigDisable:.spec.defaultConfigDisable, defaultConfig:.spec.defaultConfig,
     matchRules:.spec.matchRules}'
```

如果 Secret 为空或不正确，且 Console 编辑界面没有该字段，补充到刚刚创建的同一个资源：

```bash
kubectl --context higress-dev -n higress-system patch wasmplugin "$PLUGIN_CR" \
  --type=merge -p '{"spec":{"imagePullSecret":"codex-private-wasm-pull"}}'
```

已有 Console 配置的默认拉取 Secret 不应被当作保证，特别是自定义插件必须检查最终 CR。后续在 Console 保存后，也可再核对该字段。

## 10. 请求验证：不仅看页面开关

### 10.1 启用后应答改变

```bash
curl --noproxy '*' -i -H 'Host: wasm-demo.local' \
  http://127.0.0.1:18081/hello
```

预期：

```text
HTTP/1.1 200 OK
x-leon-wasm: 0.1.0

Hello from Console!
```

这证明自定义代码被执行，而不只是后端自己返回 200。

### 10.2 其他路径继续转发

```bash
curl --noproxy '*' -i -H 'Host: wasm-demo.local' \
  http://127.0.0.1:18081/pass
```

预期为 HTTP 200 和 `hello-from-backend`，没有插件响应头。

### 10.3 在 Console 热更新配置

把 `message` 改成 `Hello version two!`，保持 `blocked: false`，保存后重复请求 `/hello`。预期正文改变；无需重新编译或重启 Gateway。

然后把 `blocked` 改成 `true` 再保存：

```bash
curl --noproxy '*' -i -H 'Host: wasm-demo.local' \
  http://127.0.0.1:18081/hello
```

预期 HTTP 403、`x-leon-wasm: 0.1.0`、正文 `Blocked by leon-hello`。

### 10.4 关闭插件做对照

在 Console 中关闭此插件，再请求 `/hello`，预期恢复 `hello-from-backend`。验证完成后按需重新启用，并把 `blocked` 恢复为 false。

如果你使用的是域名级配置，必须修改或关闭对应域名规则，不要只改另一个未命中的全局配置。

## 11. 检查加载、xDS 和请求日志

检查动态扩展更新指标：

```bash
kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS http://127.0.0.1:15000/stats |
grep -E 'leon-hello.*(update_success|update_rejected|config_fail):'
```

成功应看到 `update_success` 增加，当前操作不再增加 `config_fail/update_rejected`。失败计数是累计值，不要求修复后自动归零。

查看 Envoy 已加载的 ECDS 名称，不输出插件密钥或完整配置：

```bash
kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS http://127.0.0.1:15000/config_dump |
jq '.configs[] | .ecds_filters[]? | .ecds_filter
    | select(.name | contains("leon-hello"))
    | {resource:.name, plugin:.typed_config.config.name}'
```

确认生效 Listener 引用了插件：

```bash
kubectl --context higress-dev -n higress-system exec \
  deployment/higress-gateway -c higress-gateway -- \
  curl -fsS http://127.0.0.1:15000/config_dump |
jq '.configs[] | .dynamic_listeners[]? | .active_state.listener?
    | .. | objects | .http_filters[]?
    | select(.name | contains("leon-hello")) | .name'
```

查看请求访问日志：

```bash
kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway --since=10m |
jq -R 'fromjson?
  | select(.authority == "wasm-demo.local")
  | {request_id, path, response_code, response_code_details, route_name, upstream_host}'
```

命中本地应答时 detail 应能关联 `leon-hello.reply` 或 `leon-hello.blocked`；实际前缀取决于 Gateway 版本。`/pass` 应访问后端。这种对照比单纯查看 200/403 更能说明插件是否执行。

排查加载错误：

```bash
kubectl --context higress-dev -n higress-system logs \
  deployment/higress-gateway -c higress-gateway --since=10m |
grep -E 'leon-hello|Unable to create Wasm|failed to load|invalid media type|missing image pulling secret'
```

没有成功日志不代表未加载，需结合 ECDS、生效 Listener 和行为验证。如果其他全局插件仍有错误，也可能使 Listener 更新被拒绝。

## 12. 可选：直接用 YAML 部署同一插件

主线是通过 Console 添加，本节用于理解底层 CR 或在 Console 不可用时部署。**不要与第 9 节重复创建两个执行同一逻辑的插件。**若已由 Console 创建，请编辑它生成的资源，不要再 apply 下面的新资源。

```bash
cat > wasmplugin.yaml <<'EOF'
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: leon-hello
  namespace: higress-system
spec:
  url: oci://codex-private-wasm-registry.higress-system.svc.cluster.local:5000/plugins/leon-hello:0.1.0
  imagePullSecret: codex-private-wasm-pull
  phase: UNSPECIFIED_PHASE
  priority: 100
  failStrategy: FAIL_OPEN
  defaultConfigDisable: true
  defaultConfig:
    allowed_host: wasm-demo.local
    message: Hello from YAML!
    blocked: false
  matchRules:
    - domain:
        - wasm-demo.local
      configDisable: false
      config:
        allowed_host: wasm-demo.local
        message: Hello from YAML!
        blocked: false
EOF

kubectl --context higress-dev apply --dry-run=server -f wasmplugin.yaml
kubectl --context higress-dev apply -f wasmplugin.yaml
```

`defaultConfigDisable: true` 禁止全局执行，只有测试域名规则启用。本示例选择 FAIL_OPEN 方便学习；其含义是加载失败可能放行，因此“请求返回 200”不能单独证明插件有效。

本例不显式设置 imagePullPolicy，使用当前 Higress 默认策略；每次代码升级使用新标签。不要忽略服务端 dry-run 的 CRD 校验错误继续部署。

## 13. 升级与清理

修改插件代码后重新编译，并使用新的镜像标签，例如 `0.1.1`；同步更新源码响应头的版本。重新执行构建与推送时替换标签，在 Console 卡片菜单的“编辑”中改镜像 URL，等待 xDS 更新，再验收请求。不推荐覆盖原标签后依赖缓存刷新。

只修改 `message/blocked` 属于配置更新，不需要重新编译或更换镜像。

清理步骤由你按需执行：先在 Console 关闭并删除 `leon-hello` 自定义插件，再删除测试后端和路由：

```bash
cd /home/teaho/IdeaProjects/teaho-infra/higress-ai-demo/wasm/leon-hello
kubectl --context higress-dev delete -f backend.yaml
```

只有采用第 12 节直接部署的路径时，才执行：

```bash
kubectl --context higress-dev delete -f wasmplugin.yaml
```

对终端 C、D 按 Ctrl+C 结束转发。保留共享 Registry、Secret、Higress 和其他模型路由。

## 14. 完成记录

由你执行后填写，不预先标记成功：

- [ ] 三个 Higress 组件 Ready，Registry 和 Secret 正常。
- [ ] Go 编译成功，生成 `plugin.wasm` 和 `go.sum`。
- [ ] 镜像上传成功，Registry Manifest 的层格式检查通过。
- [ ] 未启用插件时 `/hello` 返回 `hello-from-backend`。
- [ ] Console 创建了自定义插件并保存了正确的 URL 和 Secret。
- [ ] 启用后 `/hello` 返回配置问候语和插件响应头。
- [ ] `/pass` 继续返回后端响应。
- [ ] 修改 message 热更新成功，blocked=true 时返回 403。
- [ ] ECDS 和 active Listener 中出现插件，当前更新没有新增拒绝。
- [ ] 关闭插件后 `/hello` 恢复后端响应。

可记录：执行日期、镜像 tag/digest、生成的 WasmPlugin 名称、HTTP 结果、失败原因及最终修复命令。

## 参考资料

- [Higress 自定义插件：构建和 Console 创建入口](https://higress.ai/docs/latest/plugins/custom/)
- [Higress v2.2.4 request-block 回调示例](https://github.com/higress-group/higress/blob/v2.2.4/plugins/wasm-go/examples/request-block/main.go)
- [Higress v2.2.4 request-block 依赖版本](https://github.com/higress-group/higress/blob/v2.2.4/plugins/wasm-go/examples/request-block/go.mod)
- [Higress v2.2.4 本地 Go Wasm 构建目标](https://github.com/higress-group/higress/blob/v2.2.4/plugins/wasm-go/Makefile)
- [本项目集群与私有 Registry 实跑指南](minikube-source-build-cluster-codex.md)
