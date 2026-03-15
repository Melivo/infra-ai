# infra-ai

Minimales lokales Inference-Backend fuer den quantisierten `Qwen/Qwen3-14B-AWQ` mit `vLLM` und OpenAI-kompatibler API auf `http://localhost:8000/v1`.

## Struktur

```text
infra-ai/
  vllm/
    docker-compose.yml
    start.sh
    .env.example
  router/
    app.py
    policies.py
    schemas.py
    providers/
      base.py
      local_vllm.py
      openai_fallback.py
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
2. Trage `HUGGING_FACE_HUB_TOKEN` in `vllm/.env` ein, falls du private oder rate-limitierte Hugging-Face-Artefakte brauchst.

## Server starten

```bash
docker compose -f vllm/docker-compose.yml --env-file vllm/.env up -d
```

Der Container heisst `vllm-qwen` und exponiert Port `8000`.

## Router

Der Router ist die duenne Kontrollschicht oberhalb von vLLM. Er nimmt Requests zentral an, leitet sie lokal an vLLM weiter und bereitet spaetere Provider- und Fallback-Logik vor, ohne die Inference-Schicht zu vermischen.

```bash
python -m router.app
```

Standardmaessig lauscht der Router auf `http://127.0.0.1:8010` und leitet an `http://127.0.0.1:8000/v1` weiter.

Aktuell exponiert er:

- `GET /healthz`
- `GET /v1/models`
- `POST /v1/chat/completions`

Die OpenAI-Fallback-Schnittstelle ist nur vorbereitet. `OPENAI_API_KEY` bleibt privat und gehoert nicht in dieses public Repo.

## Default-Modell

Das lokale Default-Modell ist `Qwen/Qwen3-14B-AWQ`, weil es auf einer einzelnen RTX 4090 (24 GB VRAM) stabil startet und als schneller lokaler Standard fuer den AI-Hub taugt.

Groessere Modelle wie `Qwen3-32B` und darueber sind fuer Multi-GPU-Setups, Cloud-Inference oder einen OpenAI-Fallback gedacht.

## Healthcheck

```bash
curl http://localhost:8000/v1/models
```

Router-Healthcheck:

```bash
curl http://localhost:8010/healthz
curl http://localhost:8010/v1/models
```

## Test-Client

```bash
python -m pip install openai
python scripts/test_inference.py
```

Ueber den Router testen:

```bash
INFRA_AI_BASE_URL=http://localhost:8010/v1 python scripts/test_inference.py
```

## Lokale Checks

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Hinweise

- `vllm/.env` ist lokal und darf nicht committed werden.
- Das Single-4090-Setup nutzt `Qwen/Qwen3-14B-AWQ` mit `awq_marlin`.
- Die Speichereinstellungen sind bewusst auf stabile Starts mit einer einzelnen RTX 4090 ausgelegt.
- `--enforce-eager` ist auf Single-4090-Desktop-Systemen aktiviert, um Startup-OOMs waehrend Compile- und Autotuning-Phasen zu vermeiden.
- Der Router und die Provider-Abstraktion sind public-repo-tauglich; echte `OPENAI_API_KEY`-Werte, proprietaere Prompts und private Workflow-Daten bleiben privat.
- Die vLLM-Parameter sind fuer eine einzelne RTX 4090 (24 GB VRAM) abgestimmt.
- `--trust-remote-code` ist fuer `Qwen/Qwen3-14B-AWQ` aktiviert.
