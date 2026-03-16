# infra-ai

`infra-ai` ist ein lokaler AI-Hub mit einem zentralen Router als Infrastruktur-Schicht.

Die aktuelle Zielarchitektur ist bewusst klein gehalten und frontend-agnostisch:

- Default lokal ueber `vLLM`
- Reasoning-Fallback ueber `Gemini API`
- Heavy-Reasoning-Fallback ueber `OpenAI API`
- mehrere Frontends, inklusive Terminal und spaeterem IDE-Chat, sprechen nur mit dem Router

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
  docs/
    frontends.md
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
Terminal CLI ----\
                  -> Router API -> local_vllm
Code OSS IDE ----/             -> gemini_fallback
                                -> openai_responses
```

Wichtige Leitplanken:

- Die CLI ist ein Referenz-Frontend, nicht das einzige Frontend.
- Eine spaetere Code-OSS-Integration ist ebenfalls nur ein Frontend vor dem Router.
- Provider-Logik bleibt im Backend.
- `vLLM` bleibt lokal und zustandsarm.
- API-Provider sind optional konfigurierbar.
- Keine stillen Cloud-Fallbacks: der Request bestimmt den Routing-Modus explizit.
- Streaming ist minimal ueber den Router verfuegbar, aktuell nur fuer den lokalen Pfad.
- Alle Frontends nutzen denselben Router-Vertrag fuer Chat, Routing und Capabilities.

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

Wenn du Cloud-Provider aktivierst, validiert der Router die notwendige Konfiguration beim Start fail-fast und beendet sich mit einer klaren Fehlermeldung, statt erst beim ersten Request halb-konfiguriert zu scheitern.

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

Alternativ kannst du den lokalen Stack mit kleinen Helfern starten und stoppen:

```bash
bash scripts/start.sh
bash scripts/stop.sh
```

`scripts/start.sh` startet `vLLM` und den Router im Hintergrund. Der Router schreibt dabei nach `~/.ai/logs/router.log`.
Falls `.venv` noch nicht existiert, legt das Skript sie an und installiert `requirements.txt`, bevor der Router gestartet wird.
Die Router-PID liegt stabil unter `~/.ai/run/router.pid`; das Script prueft ausserdem, ob diese PID wirklich zu `router.app` gehoert, bevor es einen zweiten Start blockiert oder beim Stoppen beendet.
Vor dem Docker-Start prueft das Script ausserdem, ob `nvidia-smi` funktioniert und ob `/run/nvidia-persistenced/socket` vorhanden ist. Falls nicht, bekommst du einen klaren Hinweis statt eines spaeteren OCI-Fehlers.

Aktuell exponiert er:

- `GET /healthz`
- `GET /v1/router/capabilities`
- `GET /v1/models`
- `POST /v1/chat/completions`

`GET /v1/models` ist aktuell ein kleiner Kompatibilitaetspfad fuer lokale Modell-Discovery ueber den Router und wird derzeit an `local_vllm` gebunden. Der Endpunkt ist damit noch kein aggregiertes Multi-Provider-Discovery-API des gesamten Routers.

## Current Platform Guarantees

Der aktuelle Router-Vertrag ist bewusst klein, aber hart:

- Der Router ist frontend-agnostisch und die einzige Stelle mit Modell-, Provider- und Routing-Logik.
- Oeffentliche Endpunkte sind aktuell `GET /healthz`, `GET /v1/router/capabilities`, `GET /v1/models` und `POST /v1/chat/completions`.
- `POST /v1/chat/completions` wird frueh und strikt validiert, bevor Providerlogik ausgefuehrt wird.
- Fehler werden fuer Frontends konsistent als `{"error":{"type":"...","message":"..."}}` ausgegeben.
- Provideraufrufe unterliegen einem routergesteuerten Timeout ueber `INFRA_AI_REQUEST_TIMEOUT_S`.
- Streaming ist aktuell nur fuer den lokalen Pfad ueber den Router vorgesehen.
- `GET /v1/models` bleibt vorerst ein lokaler Kompatibilitaetspfad und ist noch kein aggregiertes Multi-Provider-Discovery-API.
- Bewusst noch nicht enthalten sind Tool-Use, Agents, MCP, RAG und intelligente Autowahl zwischen Providern.

## Repository Layout

Dieses Repository enthaelt die oeffentliche Infrastruktur von `infra-ai`:

- Router
- Provider-Abstraktionen
- CLI
- Beispielkonfigurationen
- Dokumentation
- generische Skripte und Tests

Private Inhalte wie Secrets, produktive Prompts, Kundendaten oder private Wissensdaten gehoeren in separate private Repositories. Details dazu stehen in [docs/repositories.md](/home/visimeos/Projects/infra-ai/docs/repositories.md).

## Router-Introspection

`GET /v1/router/capabilities` ist ein read-only Introspection-Endpunkt fuer CLI und spaetere Frontends.

Er liefert nur oeffentliche, aus der aktuellen Konfiguration ableitbare Informationen, zum Beispiel:

- `frontend_contract`
- `available_routes`
- `enabled_providers`
- `streaming_support`
- `default_models`
- `schema_version`
- `router_version`
- `not_yet_supported`

Die Antwort enthaelt bewusst keine Secrets, keine API-Keys und keine sensitiven Provider-Credentials.

Der `frontend_contract`-Block macht explizit sichtbar, dass der Router fuer mehrere Clients gedacht ist und welche Endpunkte bzw. Regeln gemeinsam fuer Terminal und spaetere IDE-Frontends gelten.

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

## Tools

`infra-ai` unterstuetzt einen modularen Tool Execution Layer.

Tools werden nicht direkt im Router implementiert. Stattdessen werden sie ueber eine zentrale Registry registriert und durch eine Policy kontrolliert.

```text
ToolCall
-> ToolOrchestrator
-> ToolRegistry
-> ToolPolicy
-> ToolExecutor
```

Ein Tool besteht aus drei Teilen:

- `ToolSpec` beschreibt das Tool.
- `ToolExecutor` implementiert die Ausfuehrung.
- die Registrierung in der `ToolRegistry` macht das Tool fuer die Laufzeit verfuegbar.

Die eigentliche Implementierung eines Tools ist bewusst vom Router entkoppelt.

Eine detaillierte Anleitung zum Schreiben eines Tools steht in [docs/tools.md](/home/visimeos/Projects/infra-ai/docs/tools.md).

Aktuell ist die Router-Integration bewusst klein:

- `POST /v1/chat/completions` akzeptiert optional ein Feld `tool_call`
- `POST /v1/chat/completions` akzeptiert optional ein Feld `allowed_tools`
- derzeit ist nur das Beispieltool `echo` registriert
- `tool_call` ist ein expliziter Router-Pfad und noch keine allgemeine LLM-Tool-Calling-Implementierung
- `GET /v1/router/capabilities` liefert kleine Tool-Metadaten fuer spaetere Frontend-Auswahl
- eine spaetere klickbare oder waehlbare Tool-UI gehoert ins CLI/TUI-Frontend, nicht in den Router

Beispiel:

```json
{
  "model": "auto",
  "messages": [
    {
      "role": "user",
      "content": "Run the echo tool."
    }
  ],
  "tool_call": {
    "name": "echo",
    "arguments": {
      "message": "hello"
    }
  },
  "allowed_tools": ["echo"]
}
```

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

## Request-Contract

Der Router validiert `POST /v1/chat/completions` bewusst frueh und strikt:

- `messages` ist verpflichtend und muss ein nicht-leeres JSON-Array sein.
- Jede Message braucht `role` und `content`.
- Aktuell sind nur `system`, `user` und `assistant` als Rollen erlaubt.
- Aktuell ist nur Text-Content erlaubt: entweder als String oder als Liste aus Text-Teilen.
- `stream` muss, falls gesetzt, ein Boolean sein.
- `model` muss, falls gesetzt, ein nicht-leerer String sein. Fuer Router-Defaults bleibt `model=auto` erlaubt.
- `provider_slot` ist ein internes Router-Feld und darf nicht von Clients gesendet werden.

Semantisch kaputte oder mehrdeutige Requests werden mit konsistenten `4xx`-Antworten im Format
`{"error":{"type":"...","message":"..."}}` abgelehnt, statt still normalisiert oder implizit umgedeutet zu werden.

## Error- und Timeout-Contract

Providerbedingte Fehler werden an der Router-Grenze normalisiert. Frontends sehen dadurch keine rohen Upstream-Fehlerstrukturen, sondern stabile Typen wie zum Beispiel:

- `provider_error`
- `provider_unavailable`
- `upstream_bad_response`
- `auth_error`
- `rate_limited`
- `timeout`
- `streaming_not_supported`

Timeouts fuer Upstream-Provider werden vom Router ueber `INFRA_AI_REQUEST_TIMEOUT_S` kontrolliert und als konsistenter `504`-Fehler mit `error.type=timeout` sichtbar.

## Betriebslogs

Der Router schreibt minimale strukturierte JSON-Logs fuer:

- Router-Start
- eingehende validierte Chat-Requests
- gewaehlte Route und Provider
- Provider-Fehler und Timeout-Faelle

Die Logs enthalten bewusst keine Prompt-Inhalte, keine API-Keys und keine sonstigen Secrets.

## Minimale CLI

Die CLI ist ein bewusst duennes Referenz-Frontend und enthaelt keine Provider- oder Agentenlogik.

```bash
python3 -m cli.main --route local "Fasse in einem Satz zusammen, wofuer infra-ai gebaut ist."
```

Capabilities abrufen:

```bash
python3 -m cli.main --capabilities
```

## CLI Tool Selection

`infra-ai` CLI laedt verfuegbare Tools ueber `GET /v1/router/capabilities` und bietet beim Start eine kleine Terminal-Auswahl an.

Die Auswahl wird als `allowed_tools` an den Router gesendet. Die eigentliche Tool-Freigabe und Tool-Kontrolle bleibt im Router. Eine spaetere klickbare oder reichere Tool-UI gehoert in ein Frontend wie eine TUI, nicht in den Router selbst.

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

## Mehrere Frontends

infra-ai ist jetzt explizit als Router-Plattform fuer mehrere Frontends positioniert:

- Terminal-CLI ist das heutige Referenz-Frontend.
- ein spaeterer Chat in Code OSS ist als zusaetzliches Frontend vorgesehen.
- beide sollen denselben Router-Vertrag verwenden.
- weder CLI noch IDE duplizieren Provider- oder Modelllogik.

Die Frontend-Grenze ist separat beschrieben in [docs/frontends.md](/home/visimeos/Projects/infra-ai/docs/frontends.md).

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
- Doku fuer spaetere Frontends wie Code OSS
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
