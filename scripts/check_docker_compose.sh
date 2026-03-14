#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

docker compose \
  -f "${REPO_ROOT}/vllm/docker-compose.yml" \
  --env-file "${REPO_ROOT}/vllm/.env" \
  config >/dev/null
