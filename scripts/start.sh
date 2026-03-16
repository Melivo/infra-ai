#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${HOME}/.ai/run"
PID_FILE="${RUN_DIR}/router.pid"
ROUTER_LOG_DIR="${HOME}/.ai/logs"
ROUTER_LOG_FILE="${ROUTER_LOG_DIR}/router.log"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"

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

mkdir -p "${HOME}/.ai/models" "${HOME}/.ai/cache" "${ROUTER_LOG_DIR}" "${RUN_DIR}"

if [[ ! -f "${REPO_ROOT}/vllm/.env" ]]; then
  echo "missing vllm/.env; copy vllm/.env.example first" >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

if [[ -f "${REPO_ROOT}/requirements.txt" ]]; then
  "${PYTHON_BIN}" -m pip install -r "${REPO_ROOT}/requirements.txt"
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
  if is_router_process "${existing_pid}"; then
    echo "router already running with pid ${existing_pid}"
    echo "vLLM started or already running"
    echo "router log: ${ROUTER_LOG_FILE}"
    exit 0
  fi
  if kill -0 "${existing_pid}" 2>/dev/null; then
    echo "pid file ${PID_FILE} points to a different live process (${existing_pid}); refusing to start a second router" >&2
    exit 1
  fi
  echo "removing stale router pid file ${PID_FILE}"
  rm -f "${PID_FILE}"
fi

nohup "${PYTHON_BIN}" -m router.app >"${ROUTER_LOG_FILE}" 2>&1 &
router_pid="$!"
echo "${router_pid}" > "${PID_FILE}"

echo "vLLM started"
echo "python environment ready at ${VENV_DIR}"
echo "router started with pid ${router_pid}"
echo "router pid file: ${PID_FILE}"
echo "router log: ${ROUTER_LOG_FILE}"
