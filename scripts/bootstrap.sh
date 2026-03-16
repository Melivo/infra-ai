#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
REQUIREMENTS_FILE="${REPO_ROOT}/requirements.txt"
REQUIREMENTS_STAMP_FILE="${VENV_DIR}/.infra-ai-requirements.sha256"

requirements_hash() {
  sha256sum "${REQUIREMENTS_FILE}" | awk '{print $1}'
}

cd "${REPO_ROOT}"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

if [[ -f "${REQUIREMENTS_FILE}" ]]; then
  "${PYTHON_BIN}" -m pip install -r "${REQUIREMENTS_FILE}"
  requirements_hash > "${REQUIREMENTS_STAMP_FILE}"
  echo "python dependencies bootstrapped from ${REQUIREMENTS_FILE}"
else
  rm -f "${REQUIREMENTS_STAMP_FILE}"
  echo "python environment ready at ${VENV_DIR}"
fi
