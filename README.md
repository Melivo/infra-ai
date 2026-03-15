# infra-ai

Minimales lokales Inference-Backend fuer `Qwen/Qwen3-32B` mit `vLLM` und OpenAI-kompatibler API auf `http://localhost:8000/v1`.

## Struktur

```text
infra-ai/
  vllm/
    docker-compose.yml
    start.sh
    .env.example
  scripts/
    healthcheck.sh
    test_inference.py
  .github/
    workflows/
      ci.yml
```

## Runtime-Daten

Die Laufzeitdaten liegen bewusst ausserhalb von Git:

- `~/.ai/models`
- `~/.ai/cache`
- `~/.ai/logs`

## Vorbereitung

Alle Befehle unten werden vom Repository-Root aus ausgefuehrt.

1. `cp vllm/.env.example vllm/.env`
2. Trage `HF_TOKEN` in `vllm/.env` ein, falls du private oder rate-limitierte Hugging-Face-Artefakte brauchst.

## Server starten

```bash
docker compose -f vllm/docker-compose.yml --env-file vllm/.env up -d
```

Der Container heisst `vllm-qwen` und exponiert Port `8000`.

## Healthcheck

```bash
curl http://localhost:8000/v1/models
```

## Test-Client

```bash
python -m pip install openai
python scripts/test_inference.py
```

## Lokale Checks

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Hinweise

- `vllm/.env` ist lokal und darf nicht committed werden.
- Die vLLM-Parameter sind fuer eine einzelne RTX 4090 (24 GB VRAM) abgestimmt.
- `--trust-remote-code` ist fuer `Qwen/Qwen3-32B` aktiviert.
