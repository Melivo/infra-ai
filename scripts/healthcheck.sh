#!/usr/bin/env bash
set -euo pipefail

curl --fail --silent --show-error http://localhost:8000/v1/models
