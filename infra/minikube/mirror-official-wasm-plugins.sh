#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )); then
  echo "Usage: $0 <plugins.properties> <destination-registry-config>" >&2
  exit 2
fi

plugin_list=$1
registry_config=$2
destination=localhost:15006/plugins
source_prefix=oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/

if [[ ! -r "$plugin_list" || ! -r "$registry_config" ]]; then
  echo "Plugin list and destination registry config must be readable" >&2
  exit 2
fi

count=0
while IFS='=' read -r plugin_name image_url || [[ -n "$plugin_name" ]]; do
  [[ -z "$plugin_name" || "$plugin_name" == \#* ]] && continue
  [[ "$image_url" == "$source_prefix"* ]] || {
    echo "Unexpected image URL for $plugin_name: $image_url" >&2
    exit 1
  }

  source_ref=${image_url#oci://}
  target_ref=$destination/${image_url#"$source_prefix"}
  source_digest=
  for attempt in 1 2 3 4 5; do
    if source_digest=$(oras resolve "$source_ref" 2>/dev/null); then
      break
    fi
    if (( attempt == 5 )); then
      echo "Unable to resolve source digest after 5 attempts: $source_ref" >&2
      exit 1
    fi
    sleep 2
  done
  target_digest=$(oras resolve --plain-http --registry-config "$registry_config" "$target_ref" 2>/dev/null || true)

  if [[ "$target_digest" != "$source_digest" ]]; then
    for attempt in 1 2 3; do
      if oras cp --no-tty --to-plain-http --to-registry-config "$registry_config" \
        "$source_ref" "$target_ref" >/dev/null; then
        break
      fi
      if (( attempt == 3 )); then
        echo "Copy failed after 3 attempts: $source_ref" >&2
        exit 1
      fi
      sleep 2
    done
    target_digest=$(oras resolve --plain-http --registry-config "$registry_config" "$target_ref")
    [[ "$target_digest" == "$source_digest" ]] || {
      echo "Digest mismatch: $target_ref" >&2
      exit 1
    }
  fi

  count=$((count + 1))
  printf '%02d %s %s\n' "$count" "$plugin_name" "$target_digest"
done < "$plugin_list"

echo "Verified $count plugin artifacts"
