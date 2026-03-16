# Tools

Der Tool Execution Layer von `infra-ai` bleibt router-zentriert.

Der Router ist die einzige Instanz, die Tool-Calls erkennt, prueft und ausfuehrt. Frontends liefern nur Requests und optional `allowed_tools`. Provider liefern Rohantworten, aber keine Tool-Steuerung.

## V1-Stand

Der aktuelle V1-Flow ist jetzt in den normalen Router-Request-Pfad integriert:

```text
Chat Request
-> Provider Adapter
-> NormalizedGeneration
-> ToolLoopEngine
-> ToolOrchestrator
-> ToolRegistry
-> ToolPolicy
-> ToolExecutor
-> ToolResult
-> Tool-Nachricht zurueck in den Modellkontext
```

Der bisherige explizite Debug-Pfad ueber `tool_call` in `POST /v1/chat/completions` bleibt weiterhin erhalten und nutzt dieselbe Tool-Ausfuehrungsschicht.

## Interne Bausteine

- `NormalizedToolCall`, `NormalizedMessage`, `NormalizedGeneration`, `GenerationRequest` in `router/normalization.py`
- `ToolSpec`, `ToolCall`, `ToolResult`, `ToolContext`, `ToolExecutor` in `router/tools/types.py`
- `ToolRegistry` in `router/tools/registry.py`
- `ToolPolicy` in `router/tools/policy.py`
- `ToolOrchestrator` in `router/tools/orchestrator.py`
- `ToolLoopEngine` in `router/tool_loop.py`

## Router-Verhalten

V1 unterstuetzt:

- provider-unabhaengige Normalisierung von Modellantworten
- automatische Erkennung genau eines Tool-Calls pro Modellschritt
- Allowlist-Nutzung ueber `allowed_tools`
- Policy- und Schema-Validierung vor der Tool-Ausfuehrung
- kleine Wiederholungserkennung fuer identische Tool-Calls ohne Fortschritt
- Rueckgabe des Tool-Results in den Modellkontext als interne Tool-Nachricht mit stabilem JSON-Pfad
- Abbruch nach `INFRA_AI_MAX_TOOL_STEPS`
- Tool-Timeout ueber `INFRA_AI_TOOL_TIMEOUT_S`

V1 unterstuetzt bewusst noch nicht:

- mehrere Tool-Calls in einem Modellschritt
- parallele Tool-Calls
- persistente Agent-Memory
- MCP
- RAG
- Workflow- oder Background-Engines

## Normalisierte Datenmodelle

Der Router arbeitet intern nicht direkt mit OpenAI-, Gemini- oder vLLM-Rohformaten.

- `NormalizedMessage` bildet System-, User-, Assistant- und Tool-Nachrichten ab.
- `NormalizedToolCall` bildet einen einzelnen provider-unabhaengigen Tool-Aufruf ab.
- `NormalizedGeneration` kapselt die normalisierte Modellantwort eines Schritts inklusive optionaler Tool-Calls und Metadaten.
- `GenerationRequest` beschreibt den provider-unabhaengigen Input fuer den naechsten Modellschritt inklusive normalisierter Nachrichten und der erlaubten Tool-Spezifikationen.
- Fuer Tool-Result-Nachrichten ist `content_json` das interne Primaerformat; Provider-Adapter serialisieren strukturierte Inhalte erst an ihrer jeweiligen Grenze in Text.

## Fehlervertrag

Der Router liefert Tool-Loop-Fehler weiterhin im bestehenden Error-Envelope:

```json
{
  "error": {
    "type": "tool_not_allowed",
    "message": "..."
  }
}
```

V1 behandelt dabei mindestens:

- `tool_not_found`
- `tool_not_allowed`
- `invalid_tool_arguments`
- `tool_execution_failed`
- `tool_timeout`
- `max_tool_steps_exceeded`
- `invalid_model_tool_call`
- `tool_loop_repeated_call_detected`

## Aktuelles Beispieltool

Der Router registriert aktuell zwei kleine Beispieltools:

- `echo`
- `add_numbers`

`echo` gibt die uebergebenen Argumente unveraendert als `ToolResult` zurueck.

`add_numbers` addiert zwei numerische Felder `a` und `b` mit einem strengen Input-Vertrag. Das Tool dient als deterministisches Beispiel fuer Tool-Loop, Validierung und Fehlerfaelle.

## Ausblick

Die aktuelle Normalisierungsschicht ist bewusst klein gehalten, damit spaetere Erweiterungen wie MCP-, RAG- oder Agent-Layer auf derselben Router-internen Struktur aufsetzen koennen, ohne Frontend- oder Provider-Logik zu vermischen.
