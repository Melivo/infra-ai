#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${HOME}/.ai/run"
PID_FILE="${RUN_DIR}/router.pid"

is_router_process() {
  local pid="$1"
  local args
  if ! kill -0 "${pid}" 2>/dev/null; then
    return 1
  fi
  args="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
  [[ "${args}" == *"router.app"* ]]
}

cd "${REPO_ROOT}"

if [[ -f "${PID_FILE}" ]]; then
  router_pid="$(cat "${PID_FILE}")"
  if is_router_process "${router_pid}"; then
    kill "${router_pid}"
    echo "router stopped (${router_pid})"
  elif kill -0 "${router_pid}" 2>/dev/null; then
    echo "pid file ${PID_FILE} points to a different live process (${router_pid}); not killing it"
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
