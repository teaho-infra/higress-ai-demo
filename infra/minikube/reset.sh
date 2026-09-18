#!/usr/bin/env bash
# =============================================================================
# Higress AI Demo — 重置 (reset) — 删除 minikube 集群(含全部镜像), 从零重建
# ⚠️ 破坏性: 删除集群。镜像在宿主 docker 里仍保留(源码镜像), 集群重建后需重新 image load。
#    旧 wso2 容器不受影响(它们不在 minikube 里)。
# =============================================================================
set -euo pipefail

read -r -p "⚠️  将删除 minikube 集群(重建需重新 image load 源码镜像)。继续? [y/N] " ans
[[ "${ans,,}" == "y" ]] || { echo "已取消"; exit 0; }

log() { echo -e "\033[1;31m[reset]\033[0m $*"; }

log "删除 minikube 集群 ..."
env -i PATH="$PATH:$HOME/bin" HOME="$HOME" MINIKUBE_HOME="$HOME/.minikube" \
  minikube delete -p minikube || true

log "完成。下次用 up.sh 重建(会自动重新 start + 部署; 镜像需重新 image load)。"
echo "提示: 宿主 docker 仍保留源码镜像:"
docker images | grep -E 'registry.local/higress|higress-console/console' || true