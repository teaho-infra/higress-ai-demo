#!/usr/bin/env bash
# =============================================================================
# Higress AI Demo — 停止 (down) — 幂等, 可随时重跑
# 停止 minikube 集群; 保留镜像/镜像/卷, 供 up.sh 快速恢复
# =============================================================================
set -euo pipefail

log() { echo -e "\033[1;33m[down]\033[0m $*"; }

if minikube status >/dev/null 2>&1; then
  log "停止 minikube ..."
  env -i PATH="$PATH:$HOME/bin" HOME="$HOME" MINIKUBE_HOME="$HOME/.minikube" \
    minikube stop
  log "minikube 已停止 (可随时用 up.sh 恢复)"
else
  log "minikube 未在运行"
fi