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
      openai/
        __init__.py
        responses.py
        realtime.py
        models.py
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
    -> openai_responses
```

Wichtige Leitplanken:

- Die CLI ist nur ein Client vor dem Router.
- Provider-Logik bleibt im Backend.
- `vLLM` bleibt lokal und zustandsarm.
- API-Provider sind optional konfigurierbar.
- Keine stillen Cloud-Fallbacks: der Request bestimmt den Routing-Modus explizit.
- Streaming ist minimal ueber den Router verfuegbar, aktuell nur fuer den lokalen Pfad.

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
- `GET /v1/router/capabilities`
- `GET /v1/models`
- `POST /v1/chat/completions`

## Router-Introspection

`GET /v1/router/capabilities` ist ein read-only Introspection-Endpunkt fuer CLI und spaetere Frontends.

Er liefert nur oeffentliche, aus der aktuellen Konfiguration ableitbare Informationen, zum Beispiel:

- `available_routes`
- `enabled_providers`
- `streaming_support`
- `default_models`
- `schema_version`
- `router_version`
- `not_yet_supported`

Die Antwort enthaelt bewusst keine Secrets, keine API-Keys und keine sensitiven Provider-Credentials.

## OpenAI-Semantik

Die OpenAI-Seite des Routers ist bewusst feiner aufgeteilt als ein einzelner unscharfer Cloud-Slot:

- `openai_text`: normaler starker Cloud-Text, Coding und Analyse
- `openai_reasoning`: schwereres Denken und komplexere Problemloesung
- `openai_tools`: vorbereiteter spaeterer Responses-basierter Tool-Slot
- `openai_agent`: vorbereitete spaetere Agent-/Orchestrierungs-Schicht, kein normaler Inference-Endpoint
- `openai_realtime`: separater vorbereiteter Slot fuer Low-Latency / Voice / Audio / Live-Kommunikation
- `openai_models`: Discovery-/Capabilities-/Health-Pfad, kein Inference-Slot

Wichtige Trennung:

- `Responses API` ist der OpenAI-Standardpfad fuer normalen Router-basierten OpenAI-Textverkehr.
- `Realtime API` ist davon getrennt und in diesem Commit nur vorbereitet.
- `Models API` ist fuer Discovery und Introspection, nicht fuer Chat-Inferenz.
- `Agents` sind eine spaetere Orchestrierungsschicht oberhalb der Modell-API, nicht einfach ein weiterer Chat-Endpoint.

## Routing-Vertrag

`POST /v1/chat/completions` akzeptiert ein router-spezifisches Top-Level-Feld `route`:

- `auto`: deterministisch wie `local`, ohne Cloud-Fallback
- `local`: lokaler `vLLM`-Provider
- `reasoning`: `Gemini`-Provider, nur wenn aktiviert
- `heavy`: `openai_reasoning` ueber die OpenAI Responses API, nur wenn aktiviert

Wenn `reasoning` oder `heavy` angefordert werden und der jeweilige Provider nicht aktiviert ist, antwortet der Router mit einem expliziten Fehler statt still auf einen anderen Provider zu wechseln.

`model=auto` nutzt die Backend-Defaults pro Provider:

- lokal: `INFRA_AI_LOCAL_VLLM_DEFAULT_MODEL`
- Gemini: `INFRA_AI_GEMINI_DEFAULT_MODEL`
- OpenAI Text: `INFRA_AI_OPENAI_TEXT_MODEL`
- OpenAI Reasoning: `INFRA_AI_OPENAI_REASONING_MODEL`
- OpenAI Tools: `INFRA_AI_OPENAI_TOOLS_MODEL`
- OpenAI Realtime: `INFRA_AI_OPENAI_REALTIME_MODEL`

## Minimale CLI

Die CLI ist ein bewusst duennes Frontend und enthaelt keine Provider- oder Agentenlogik.

```bash
python3 -m cli.main --route local "Fasse in einem Satz zusammen, wofuer infra-ai gebaut ist."
```

Capabilities abrufen:

```bash
python3 -m cli.main --capabilities
```

Optional mit stdin:

```bash
printf 'Nenne die aktuelle Router-Architektur in einem Satz.' | python3 -m cli.main --route auto
```

Minimales lokales Streaming:

```bash
python3 -m cli.main --route local --stream "Erklaere in zwei Saetzen, was infra-ai ist."
```

Die CLI spricht standardmaessig mit `http://127.0.0.1:8010/v1`, sendet `model=auto` und reicht `route` unveraendert an den Router durch.

Aktuelle Streaming-Grenze:

- `--stream` ist fuer `local` und damit auch fuer `auto` gedacht, weil `auto` derzeit deterministisch lokal aufloest.
- Fuer `reasoning` und `heavy` liefert der Router einen klaren Fehler statt Fake-Streaming.

## Smoke-Checks

Router-Endpunkte:

```bash
bash scripts/smoke_router.sh
```

Einfacher Chat gegen den Router:

```bash
python3 scripts/smoke_chat.py
```

Mit explizitem Routing-Modus:

```bash
INFRA_AI_ROUTER_ROUTE=reasoning python3 scripts/smoke_chat.py
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
- die semantischen OpenAI-Slots und ihre API-Trennung
- CLI-Code
- Beispielkonfigurationen
- README und Smoke-Skripte
- der oeffentliche Routing-Vertrag mit `route=auto|local|reasoning|heavy`
- der oeffentliche Introspection-Vertrag von `GET /v1/router/capabilities`

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
