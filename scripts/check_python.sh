#!/usr/bin/env bash
set -euo pipefail

PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/infra-ai-pyc}"
export PYTHONPYCACHEPREFIX

python3 -m py_compile "$@"
