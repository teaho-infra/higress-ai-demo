#!/usr/bin/env bash
# =============================================================================
# Higress AI Demo — Minikube 源码构建环境 — 一键启动 (up)
# 用途: 重建/恢复到「minikube 完整集群 + 全部本地源码镜像 + 双 chart 部署」
# 前置: minikube/helm/docker 已装; ~/.docker/config.json 代理已修(见 README)
# 说明: 本脚本假定源码镜像已构建好(本地 docker tag)并使用 image load 注入。
#      需要从零构建镜像的场景见 plan/minikube-source-build-cluster.md。
# =============================================================================
set -euo pipefail

# ---- 配置 ----------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HIGRESS_SRC="${HIGRESS_SRC:-$HOME/IdeaProjects/agentspace/higress}"
CONSOLE_SRC="${CONSOLE_SRC:-$HOME/IdeaProjects/agentspace/higress-console}"
NS="higress-system"
DRIVER="${MINIKUBE_DRIVER:-docker}"
CPUS="${MINIKUBE_CPUS:-6}"
MEMORY="${MINIKUBE_MEMORY:-8192}"
DISK="${MINIKUBE_DISK:-60g}"
# 端口映射: 宿主 -> NodePort. 18080/18443/18001 保持不变
PORTS=(
  "--ports=18080:30080"
  "--ports=18443:30443"
  "--ports=18001:30001"
)

log()  { echo -e "\033[1;32m[up]\033[0m $*"; }
err()  { echo -e "\033[1;31m[up]\033[0m $*" >&2; }
die()  { err "$*"; exit 1; }

command -v minikube >/dev/null || die "minikube 未安装"
command -v helm     >/dev/null || die "helm 未安装"
command -v docker   >/dev/null || die "docker 未安装"

# ---- 0. 停掉会占端口的旧 higress 容器 (restart=always 会复活) ---------------
log "停旧 higress 容器以释放 18001/18080/18443 ..."
if docker ps -a --format '{{.Names}}' | grep -qx 'higress'; then
  docker stop higress 2>/dev/null || true
fi

# ---- 1. minikube 启动 ------------------------------------------------------
if ! minikube status >/dev/null 2>&1; then
  log "启动 minikube (driver=$DRIVER, cpus=$CPUS, mem=${MEMORY}MB) ..."
  # 用 env -i 纯净环境启动, 避免 shell 代理注入; image-mirror-country 用国内源
  env -i PATH="$PATH:$HOME/bin" HOME="$HOME" MINIKUBE_HOME="$HOME/.minikube" \
    minikube start \
      --driver="$DRIVER" --cpus="$CPUS" --memory="$MEMORY" --disk-size="$DISK" \
      "${PORTS[@]}" \
      --image-mirror-country=cn --binary-mirror=https://dl.k8s.io
else
  log "minikube 已在运行"
fi
# 裸 kubectl 需可用(指向 minikube); 若不在 PATH 则用 minikube kubectl
command -v kubectl >/dev/null || kubectl() { minikube kubectl -- "$@"; }

# ---- 2. 确认源码镜像已 load(没有则提示) -----------------------------------
log "检查本地源码镜像是否已注入 minikube ..."
for img in \
  "registry.local/higress/higress:2.2.4" \
  "registry.local/higress/pilot:2.2.4" \
  "registry.local/higress/gateway:2.2.4" \
  "higress-console/console:v2.2.4"
do
  if minikube image ls 2>/dev/null | grep -q "${img}"; then
    log "  ✓ ${img} 已在 minikube"
  else
    err "  ✗ ${img} 缺失 → 请先构建+image load (见 plan 文档)"
    MISSING=1
  fi
done
[ -z "${MISSING:-}" ] || die "有镜像缺失, 中止"

# ---- 3. 部署 core chart ---------------------------------------------------
log "部署 higress core chart (源码镜像) ..."
if ! minikube kubectl -- get ns "$NS" >/dev/null 2>&1; then
  helm install higress "$HIGRESS_SRC/helm/core" \
    -n "$NS" --create-namespace \
    -f "$REPO_ROOT/infra/minikube/higress-values.yaml"
else
  log "  ns '$NS' 已存在, 检查是否已有 release ..."
  if ! helm ls -n "$NS" | grep -q '^higress'; then
    helm install higress "$HIGRESS_SRC/helm/core" -n "$NS" \
      -f "$REPO_ROOT/infra/minikube/higress-values.yaml"
  else
    log "  higress release 已存在"
  fi
fi
minikube kubectl -- rollout status deploy/higress-controller -n "$NS" --timeout=180s || true
minikube kubectl -- rollout status deploy/higress-gateway   -n "$NS" --timeout=120s || true

# ---- 4. 部署 console chart ------------------------------------------------
log "部署 console chart (源码镜像) ..."
if ! helm ls -n "$NS" | grep -q '^console'; then
  helm install console "$CONSOLE_SRC/helm" -n "$NS" \
    -f "$REPO_ROOT/infra/minikube/console-values.yaml"
else
  log "  console release 已存在"
fi
minikube kubectl -- rollout status deploy/higress-console -n "$NS" --timeout=180s || true

# ---- 5. 免 host 访问 console (patch default ingress) -----------------------
log "配置 default ingress 指向 console (免 host 访问) ..."
kubectl patch ingress default -n "$NS" --type=json \
  -p='[{"op":"remove","path":"/metadata/annotations/higress.io~1rewrite-path"}]' 2>/dev/null || true
kubectl patch ingress default -n "$NS" --type=merge \
  -p '{"spec":{"rules":[{"http":{"paths":[{"path":"/","pathType":"Prefix","backend":{"service":{"name":"higress-console","port":{"number":8080}}}}]}}]}}' 2>/dev/null || true

# ---- 6. 数据面测试路由 (demo.local -> host.minikube.internal:9081 downstream)-
log "建立 demo 数据面路由 (宿主 downstream 9081) ..."
if docker ps -a --format '{{.Names}}' | grep -qx 'wso2-demo-downstream'; then
  docker start wso2-demo-downstream 2>/dev/null || true
  log "  wso2-demo-downstream 已启动"
fi
kubectl apply -f "$REPO_ROOT/infra/minikube/task6-downstream.yaml" 2>/dev/null || true

# ---- 7. 验证 --------------------------------------------------------------
log "验证 ..."
echo "== pods =="
kubectl get pods -n "$NS"
echo "== console(免host) =="
curl -s -o /dev/null -w '18080/ http=%{http_code}\n' --max-time 8 http://127.0.0.1:18080/ || true
echo "== downstream(数据面) =="
curl -s -o /dev/null -w '18080/demo/time http=%{http_code}\n' --max-time 8 -H 'Host: demo.local' \
  http://127.0.0.1:18080/demo/time || true

log "完成! 访问:"
echo "  Console    : http://127.0.0.1:18080/        (免 host)"
echo "  Gateway    : http://127.0.0.1:18080/ + Host: console.higress.io"
echo "  (端口映射: 18080→30080 http / 18443→30443 https / 18001→30001)"