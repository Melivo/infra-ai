#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${TMPDIR:-/tmp}/infra-ai-router.pid"

cd "${REPO_ROOT}"

if [[ -f "${PID_FILE}" ]]; then
  router_pid="$(cat "${PID_FILE}")"
  if kill -0 "${router_pid}" 2>/dev/null; then
    kill "${router_pid}"
    echo "router stopped (${router_pid})"
  else
    echo "router pid file existed, but process was not running"
  fi
  rm -f "${PID_FILE}"
else
  echo "router not running"
fi

if [[ -f "${REPO_ROOT}/vllm/.env" ]]; then
  docker compose -f "${REPO_ROOT}/vllm/docker-compose.yml" --env-file "${REPO_ROOT}/vllm/.env" down
else
  docker compose -f "${REPO_ROOT}/vllm/docker-compose.yml" down
fi

echo "vLLM stopped"
