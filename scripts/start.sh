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
REQUIREMENTS_FILE="${REPO_ROOT}/requirements.txt"
REQUIREMENTS_STAMP_FILE="${VENV_DIR}/.infra-ai-requirements.sha256"
CLI_MODE="auto"
CLI_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli)
      CLI_MODE="always"
      shift
      ;;
    --no-cli)
      CLI_MODE="never"
      shift
      ;;
    --)
      shift
      CLI_ARGS=("$@")
      break
      ;;
    *)
      echo "usage: bash scripts/start.sh [--cli|--no-cli] [-- <cli args>]" >&2
      exit 1
      ;;
  esac
done

is_router_process() {
  local pid="$1"
  local args
  if ! kill -0 "${pid}" 2>/dev/null; then
    return 1
  fi
  args="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
  [[ "${args}" == *"router.app"* ]]
}

check_nvidia_runtime() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi not found; install or expose the NVIDIA driver tools first" >&2
    exit 1
  fi

  if ! nvidia-smi -L >/dev/null 2>&1; then
    echo "NVIDIA driver is not ready; nvidia-smi cannot see the GPU" >&2
    echo "check the host driver installation before starting vLLM" >&2
    exit 1
  fi

  if [[ ! -S /run/nvidia-persistenced/socket ]]; then
    echo "missing /run/nvidia-persistenced/socket; NVIDIA persistence daemon is not ready" >&2
    echo "try: sudo systemctl enable --now nvidia-persistenced" >&2
    exit 1
  fi
}

requirements_hash() {
  sha256sum "${REQUIREMENTS_FILE}" | awk '{print $1}'
}

ensure_python_environment() {
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "python environment is not ready at ${PYTHON_BIN}" >&2
    echo "run: bash scripts/bootstrap.sh" >&2
    exit 1
  fi

  if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
    return
  fi

  if [[ ! -f "${REQUIREMENTS_STAMP_FILE}" ]]; then
    echo "python dependencies are not bootstrapped for this checkout" >&2
    echo "run: bash scripts/bootstrap.sh" >&2
    exit 1
  fi

  local current_hash
  local expected_hash
  current_hash="$(requirements_hash)"
  expected_hash="$(cat "${REQUIREMENTS_STAMP_FILE}")"
  if [[ "${current_hash}" != "${expected_hash}" ]]; then
    echo "requirements.txt changed since the last bootstrap" >&2
    echo "run: bash scripts/bootstrap.sh" >&2
    exit 1
  fi
}

wait_for_router_ready() {
  local url="$1"
  local attempts="${INFRA_AI_ROUTER_READY_RETRIES:-30}"
  local sleep_s="${INFRA_AI_ROUTER_READY_SLEEP_S:-1}"
  local attempt=1

  echo "waiting for router readiness at ${url}"

  while [[ "${attempt}" -le "${attempts}" ]]; do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi

    if [[ -f "${PID_FILE}" ]]; then
      local router_pid
      router_pid="$(cat "${PID_FILE}")"
      if ! is_router_process "${router_pid}"; then
        echo "router process exited before readiness check succeeded" >&2
        echo "router log: ${ROUTER_LOG_FILE}" >&2
        return 1
      fi
    fi

    sleep "${sleep_s}"
    attempt="$((attempt + 1))"
  done

  echo "router did not become ready after ${attempts} attempts" >&2
  echo "expected readiness endpoint: ${url}" >&2
  echo "router log: ${ROUTER_LOG_FILE}" >&2
  return 1
}

wait_for_vllm_ready() {
  local url="$1"
  local attempts="${INFRA_AI_VLLM_READY_RETRIES:-60}"
  local sleep_s="${INFRA_AI_VLLM_READY_SLEEP_S:-2}"
  local attempt=1

  echo "waiting for vLLM readiness at ${url}"

  while [[ "${attempt}" -le "${attempts}" ]]; do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_s}"
    attempt="$((attempt + 1))"
  done

  echo "vLLM did not become ready after ${attempts} attempts" >&2
  echo "expected readiness endpoint: ${url}" >&2
  echo "check: docker logs vllm-qwen" >&2
  return 1
}

should_launch_cli() {
  case "${CLI_MODE}" in
    always)
      return 0
      ;;
    never)
      return 1
      ;;
    auto)
      [[ -t 0 && -t 1 ]]
      ;;
    *)
      return 1
      ;;
  esac
}

cd "${REPO_ROOT}"

mkdir -p "${HOME}/.ai/models" "${HOME}/.ai/cache" "${ROUTER_LOG_DIR}" "${RUN_DIR}"

if [[ ! -f "${REPO_ROOT}/vllm/.env" ]]; then
  echo "missing vllm/.env; copy vllm/.env.example first" >&2
  exit 1
fi

ensure_python_environment

check_nvidia_runtime

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

ROUTER_ROOT_URL="http://${INFRA_AI_ROUTER_HOST}:${INFRA_AI_ROUTER_PORT}"
ROUTER_V1_URL="${ROUTER_ROOT_URL}/v1"
LOCAL_VLLM_READY_URL="${INFRA_AI_LOCAL_VLLM_BASE_URL%/}/models"

docker compose -f "${REPO_ROOT}/vllm/docker-compose.yml" --env-file "${REPO_ROOT}/vllm/.env" up -d

router_running=0
if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}")"
  if is_router_process "${existing_pid}"; then
    router_running=1
    echo "router already running with pid ${existing_pid}"
  fi
  if [[ "${router_running}" -eq 0 ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "pid file ${PID_FILE} points to a different live process (${existing_pid}); refusing to start a second router" >&2
    exit 1
  fi
  if [[ "${router_running}" -eq 0 ]]; then
    echo "removing stale router pid file ${PID_FILE}"
    rm -f "${PID_FILE}"
  fi
fi

if [[ "${router_running}" -eq 0 ]]; then
  nohup "${PYTHON_BIN}" -m router.app >"${ROUTER_LOG_FILE}" 2>&1 &
  router_pid="$!"
  echo "${router_pid}" > "${PID_FILE}"
  echo "router started with pid ${router_pid}"
  echo "router pid file: ${PID_FILE}"
else
  router_pid="$(cat "${PID_FILE}")"
fi

wait_for_vllm_ready "${LOCAL_VLLM_READY_URL}"
wait_for_router_ready "${ROUTER_ROOT_URL}/healthz"

echo "vLLM started"
echo "python environment ready at ${VENV_DIR}"
echo "router ready at ${ROUTER_V1_URL}"
echo "router log: ${ROUTER_LOG_FILE}"

if should_launch_cli; then
  export INFRA_AI_ROUTER_BASE_URL="${ROUTER_V1_URL}"
  echo "starting infra-ai CLI against ${INFRA_AI_ROUTER_BASE_URL}"
  if [[ ${#CLI_ARGS[@]} -eq 0 ]]; then
    exec "${PYTHON_BIN}" -m cli --interactive
  fi
  exec "${PYTHON_BIN}" -m cli "${CLI_ARGS[@]}"
fi
