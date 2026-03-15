#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/.env"
  set +a
fi

export AI_MODELS_DIR="${AI_MODELS_DIR:-${HOME}/.ai/models}"
export AI_CACHE_DIR="${AI_CACHE_DIR:-${HOME}/.ai/cache}"
export AI_LOGS_DIR="${AI_LOGS_DIR:-${HOME}/.ai/logs}"

mkdir -p "${HOME}/.ai/models" "${HOME}/.ai/cache" "${HOME}/.ai/logs"

docker compose up -d
docker compose logs -f --tail=100 vllm-qwen
