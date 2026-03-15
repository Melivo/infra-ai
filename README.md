# infra-ai

`infra-ai` ist ein lokaler AI-Hub mit einem zentralen Router als Infrastruktur-Schicht.

Die aktuelle Zielarchitektur ist bewusst klein gehalten:

- Default lokal ueber `vLLM`
- Reasoning-Fallback ueber `Gemini API`
- Heavy-Reasoning-Fallback ueber `OpenAI API`
- spaetere Frontends, inklusive Terminal-CLI, sprechen nur mit dem Router

Die fruehere Idee eines zusaetzlichen grossen lokalen Reasoning-Modells auf derselben RTX 4090 ist verworfen. `vLLM` bleibt die reine lokale Inference-Schicht fuer `Qwen/Qwen3-14B-AWQ`.

## Struktur

```text
infra-ai/
  cli/
    __init__.py
    main.py
  config/
    router.example.env
    providers.example.env
  router/
    app.py
    policies.py
    schemas.py
    providers/
      base.py
      local_vllm.py
      gemini_fallback.py
      openai_fallback.py
  scripts/
    healthcheck.sh
    smoke_chat.py
    smoke_router.sh
    test_inference.py
  vllm/
    docker-compose.yml
    start.sh
    .env.example
```

## Architektur

Der Router ist die zentrale API und Routing-Instanz.

```text
CLI / spaetere Frontends
  -> Router API
    -> local_vllm
    -> gemini_fallback
    -> openai_fallback
```

Wichtige Leitplanken:

- Die CLI ist nur ein Client vor dem Router.
- Provider-Logik bleibt im Backend.
- `vLLM` bleibt lokal und zustandsarm.
- API-Provider sind optional konfigurierbar.
- Streaming ist fuer die Router-Frontend-Schiene mitgedacht, aber in diesem Commit noch nicht implementiert.

## Runtime-Daten

Die Laufzeitdaten liegen bewusst ausserhalb von Git:

- `~/.ai/models`
- `~/.ai/cache`
- `~/.ai/logs`

## Vorbereitung

Alle Befehle unten werden vom Repository-Root ausgefuehrt.

1. `cp vllm/.env.example vllm/.env`
2. Optional: Lege lokale Konfigurationsdateien aus den Beispielen an, zum Beispiel `config/router.local.env` und `config/providers.local.env`.
3. Trage nur in lokalen, nicht versionierten Dateien echte API-Keys ein.

## vLLM starten

```bash
docker compose -f vllm/docker-compose.yml --env-file vllm/.env up -d
```

Der Container heisst `vllm-qwen` und exponiert Port `8000`.

## Router starten

Beispiel mit geladenen Env-Dateien:

```bash
set -a
source config/router.example.env
source config/providers.example.env
set +a
python3 -m router.app
```

Standardmaessig lauscht der Router auf `http://127.0.0.1:8010`.

Aktuell exponiert er:

- `GET /healthz`
- `GET /v1/models`
- `POST /v1/chat/completions`

`POST /v1/chat/completions` nutzt fuer `model=auto` die Backend-Defaults pro Provider:

- lokal: `INFRA_AI_LOCAL_VLLM_DEFAULT_MODEL`
- Gemini: `INFRA_AI_GEMINI_DEFAULT_MODEL`
- OpenAI: `INFRA_AI_OPENAI_DEFAULT_MODEL`

## Minimale CLI

Die CLI ist ein bewusst duennes Frontend und enthaelt keine Provider- oder Agentenlogik.

```bash
python3 -m cli.main "Fasse in einem Satz zusammen, wofuer infra-ai gebaut ist."
```

Optional mit stdin:

```bash
printf 'Nenne die aktuelle Router-Architektur in einem Satz.' | python3 -m cli.main
```

Die CLI spricht standardmaessig mit `http://127.0.0.1:8010/v1` und sendet `model=auto`, damit die Modelwahl backend-seitig bleibt.

## Smoke-Checks

Router-Endpunkte:

```bash
bash scripts/smoke_router.sh
```

Einfacher Chat gegen den Router:

```bash
python3 scripts/smoke_chat.py
```

Optional bleibt auch der OpenAI-SDK-Testclient verfuegbar:

```bash
python3 -m pip install openai
INFRA_AI_BASE_URL=http://localhost:8010/v1 python3 scripts/test_inference.py
```

## Public und Private

Public repo-tauglich:

- Router-Logik
- Provider-Abstraktionen
- lokaler `vLLM`-Provider
- `Gemini`- und `OpenAI`-Fallback-Schnittstellen ohne echte Secrets
- CLI-Code
- Beispielkonfigurationen
- README und Smoke-Skripte

Privat bleiben muessen:

- echte `GEMINI_API_KEY`- und `OPENAI_API_KEY`-Werte
- echte lokale `.env`-Dateien mit Secrets
- proprietaere Prompts
- private Projektkontexte, RAG-Daten und Agentenwissen
- produktive interne Ops- oder Kundendaten

## Hinweise

- `vllm/.env` ist lokal und darf nicht committed werden.
- Das Single-4090-Setup nutzt `Qwen/Qwen3-14B-AWQ` mit `awq_marlin`.
- Die Speichereinstellungen sind bewusst auf stabile Starts mit einer einzelnen RTX 4090 ausgelegt.
- `--enforce-eager` ist auf Single-4090-Desktop-Systemen aktiviert, um Startup-OOMs waehrend Compile- und Autotuning-Phasen zu vermeiden.
- `--trust-remote-code` ist fuer `Qwen/Qwen3-14B-AWQ` aktiviert.
