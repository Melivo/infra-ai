#!/usr/bin/env bash
set -euo pipefail

router_base_url="${INFRA_AI_ROUTER_BASE_URL:-http://127.0.0.1:8010/v1}"
if [[ "${router_base_url%/}" == */v1 ]]; then
  router_v1_url="${router_base_url%/}"
  router_root_url="${router_v1_url%/v1}"
else
  router_root_url="${router_base_url%/}"
  router_v1_url="${router_root_url}/v1"
fi

route="${INFRA_AI_ROUTER_ROUTE:-auto}"

curl -fsS "${router_root_url}/healthz"
echo
curl -fsS "${router_v1_url}/router/capabilities"
echo
curl -fsS "${router_v1_url}/models"
echo
curl -fsS \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"auto\",\"route\":\"${route}\",\"messages\":[{\"role\":\"user\",\"content\":\"Antworte kurz: Router erreichbar?\"}],\"temperature\":0.2,\"max_tokens\":64}" \
  "${router_v1_url}/chat/completions"
echo
