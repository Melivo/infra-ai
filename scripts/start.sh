#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${TMPDIR:-/tmp}/infra-ai-router.pid"
ROUTER_LOG_DIR="${HOME}/.ai/logs"
ROUTER_LOG_FILE="${ROUTER_LOG_DIR}/router.log"

cd "${REPO_ROOT}"

mkdir -p "${HOME}/.ai/models" "${HOME}/.ai/cache" "${ROUTER_LOG_DIR}"

if [[ ! -f "${REPO_ROOT}/vllm/.env" ]]; then
  echo "missing vllm/.env; copy vllm/.env.example first" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "${REPO_ROOT}/config/router.example.env"
# shellcheck source=/dev/null
source "${REPO_ROOT}/config/providers.example.env"
if [[ -f "${REPO_ROOT}/config/router.local.env" ]]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/config/router.local.env"
fi
if [[ -f "${REPO_ROOT}/config/providers.local.env" ]]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/config/providers.local.env"
fi
set +a

docker compose -f "${REPO_ROOT}/vllm/docker-compose.yml" --env-file "${REPO_ROOT}/vllm/.env" up -d

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}")"
  if kill -0 "${existing_pid}" 2>/dev/null; then
    echo "router already running with pid ${existing_pid}"
    echo "vLLM started or already running"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

nohup python3 -m router.app >"${ROUTER_LOG_FILE}" 2>&1 &
router_pid="$!"
echo "${router_pid}" > "${PID_FILE}"

echo "vLLM started"
echo "router started with pid ${router_pid}"
echo "router log: ${ROUTER_LOG_FILE}"
