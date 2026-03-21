# Tools

Der Tool Execution Layer von `infra-ai` bleibt router-zentriert.

Der Router ist die einzige Instanz, die Tool-Calls erkennt, prueft und ausfuehrt. Frontends liefern nur Requests und optional `allowed_tools`. Provider liefern Rohantworten, aber keine Tool-Steuerung.

## V1-Stand

Der aktuelle V1-Flow ist jetzt in den normalen Router-Request-Pfad integriert:

```text
Chat Request
-> Provider Adapter
-> ProviderOutput
-> Provider Output Parser
-> ConversationTurn / ExecutionStep
-> Declared Plan Spec
-> ExecutionPlan
-> ToolLoopEngine
-> ToolOrchestrator
-> ToolRegistry
-> ToolPolicy
-> ToolExecutor
-> ToolResult
-> Tool-Nachricht zurueck in den Modellkontext
```

Der bisherige explizite Debug-Pfad ueber `tool_call` in `POST /v1/chat/completions` bleibt weiterhin erhalten und nutzt dieselbe Tool-Ausfuehrungsschicht.

Fuer den ersten MCP-Slice kommt zusaetzlich ein separater Management-/Control-Plane-Pfad dazu:

```text
Terminal UI / MCP Servers
-> Router MCP Management
  -> Catalog Source
  -> Server Inventory
  -> Install / Enable / Disable
  -> Tool Discovery
  -> Spiegelung ready MCP-Tools in ToolRegistry
```

Wichtig:

- MCP-Server-Management ist kein normaler Tool-Call.
- Install/Enable/Disable laeuft nicht im normalen `ToolLoopEngine`.
- Erst nach erfolgreicher Discovery und Ready-State erscheinen MCP-Tools als normale Tools in der `ToolRegistry`.

## Interne Bausteine

- `ConversationTurn`, spezialisierte Turn-Typen sowie explizite `ExecutionStep`-/`ExecutionPlan`-State-Modelle in `router/conversation.py`
- `ProviderOutput` plus Parser/Validierung in `router/provider_output/`
- `NormalizedToolCall`, `NormalizedMessage`, `NormalizedGeneration`, `GenerationRequest` in `router/normalization.py` als Kompatibilitaets- und Boundary-Schicht
- `ToolSpec`, `ToolCall`, `ToolResult`, `ToolContext`, `ToolExecutor` in `router/tools/types.py`
- `ToolRegistry` in `router/tools/registry.py`
- `ToolPolicy` in `router/tools/policy.py`
- `ToolOrchestrator` in `router/tools/orchestrator.py`
- `ToolLoopEngine` in `router/tool_loop.py`

## Router-Verhalten

V1 unterstuetzt:

- provider-unabhaengige Normalisierung von Modellantworten
- automatische Erkennung von einem oder mehreren Tool-Calls pro Modellschritt
- Allowlist-Nutzung ueber `allowed_tools`
- Policy- und Schema-Validierung vor der Tool-Ausfuehrung
- kleine Wiederholungserkennung fuer identische Tool-Calls ohne Fortschritt
- Rueckgabe des Tool-Results in den Modellkontext als interne Tool-Nachricht mit stabilem JSON-Pfad
- Abbruch nach `INFRA_AI_MAX_TOOL_STEPS`
- Tool-Timeout ueber `INFRA_AI_TOOL_TIMEOUT_S`

V1 unterstuetzt bewusst noch nicht:

- parallele Tool-Calls
- persistente Agent-Memory
- RAG
- Workflow- oder Background-Engines

## Interne Datenmodelle

`ConversationTurn` ist jetzt das primaere interne Modell im Router-Kern. Provider-Rohantworten werden an der Boundary in Turns geparst, und der Tool-Loop arbeitet providerunabhaengig nur noch auf diesen Turns.

- spezialisierte Turn-Typen (`UserTurn`, `AssistantTurn`, `ToolCallTurn`, `ToolResultTurn`, `FinalTurn`) bilden die internen Rollen explizit statt ueber ein einzelnes ueberladenes Datamodell.
- `ExecutionStep` ist die autoritative Orchestrierungseinheit pro Modellschritt. Sie haelt explizit Reasoning-, Planning-, Refinement- und Finalization-Turns, die deklarative Plan-Spezifikation (`declared_plan`) sowie den aktuellen `ExecutionPlan`.
- `AssistantTurn.phase` unterscheidet explizit `reasoning`, `tool_plan`, `refinement` und `finalization`; diese Phase wird an der Provider-Boundary moeglichst direkt gesetzt statt spaeter global erraten.
- `ExecutionPlan` haelt die geplanten Tool-Calls eines Steps als explizite Knotenliste mit Strategie, Abhaengigkeiten, Knotenstatus und Ergebnisbezug.
- Jeder `ExecutionPlanNode` trennt jetzt zwischen deklarierter Planstruktur (`declared_dependencies`), zur Laufstrategie abgeleiteten Constraints (`strategy_dependencies`) und dem spaeter mutierten Fortschritt (`state`, `result`).
- In V1 bleiben deklarierte Abhaengigkeiten eine eigene Planebene. Wenn ein Tool-Call explizite `depends_on_call_ids` mitbringt, liest die Provider-Boundary diese weiterhin aus dem Payload und ueberfuehrt sie zuerst in die explizite Step-gebundene `declared_plan`-Spezifikation. Erst daraus wird der ausfuehrbare `ExecutionPlan` materialisiert; die sequentielle Reihenfolge bleibt davon getrennt als `strategy_dependencies`.
- `NormalizedMessage`, `NormalizedToolCall` und `NormalizedGeneration` bleiben als Kompatibilitaets- und API-Schicht bestehen, z. B. fuer Provider-Request-Serialisierung und den stabilen HTTP-Response-Contract.
- `GenerationRequest` haelt intern Turns und stellt Provider-Input explizit ueber `to_provider_messages()` bereit.
- Fuer Tool-Result-Nachrichten ist `content_json` das interne Primaerformat; Provider-Adapter serialisieren strukturierte Inhalte erst an ihrer jeweiligen Grenze in Text.

Mehrere Tool-Calls in einem Modellschritt werden weiterhin sequentiell gegen denselben geplanten Step ausgefuehrt. Das ist bewusst noch kein vollwertiger Tool-Graph-Executor, aber der Step enthaelt jetzt sowohl eine explizite deklarative Plan-Spezifikation als auch den daraus materialisierten `ExecutionPlan`, jeweils getrennt von Strategie- und Fortschrittsebene.

`execution_steps_from_turns()` bleibt als Kompatibilitaets- und Recovery-Pfad erhalten. Die primaere Orchestrierungsquelle ist aber nicht mehr das spaetere Erraten aus Transport-Turns, sondern der explizit erzeugte Step- und Plan-State aus dem Provider-Parser plus dessen Mutationen im Tool-Loop.

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

## Aktuell registrierte Tools

Der Router registriert aktuell zwei kleine Beispieltools:

- `echo`
- `add_numbers`

`echo` gibt die uebergebenen Argumente unveraendert als `ToolResult` zurueck.

`add_numbers` addiert zwei numerische Felder `a` und `b` mit einem strengen Input-Vertrag. Das Tool dient als deterministisches Beispiel fuer Tool-Loop, Validierung und Fehlerfaelle.

Zusaetzlich registriert Phase 1 die ersten kleinen realen Core-Tools:

- `filesystem.read`
- `filesystem.list`
- `git.status`
- `git.diff`

Diese Tools bleiben bewusst konservativ:

- `filesystem.*` ist strikt an den konfigurierten Workspace gebunden.
- `git.*` arbeitet read-only und nutzt keine mutierenden Git-Operationen.
- die neuen realen Core-Tools sind nicht `enabled_by_default` und werden erst ueber `allowed_tools` explizit fuer einen Request freigeschaltet.
- alle Tool-Outputs laufen weiter als strukturierte `content_json`-Payloads durch denselben Registry-/Policy-/Orchestrator-/Tool-Loop-Pfad.

`http.fetch` ist in diesem Schritt bewusst noch nicht registriert, weil dafuer zusaetzliche Boundary- und Security-Policy fuer Netzwerkzugriffe noetig waere, die nicht in denselben kleinen konservativen Phase-1-Scope passt.

## Ausblick

Die aktuelle Normalisierungsschicht ist bewusst klein gehalten, damit spaetere Erweiterungen wie MCP-, RAG- oder Agent-Layer auf derselben Router-internen Struktur aufsetzen koennen, ohne Frontend- oder Provider-Logik zu vermischen.

## MCP-Slice

Der erste MCP-Slice fuehrt eine kleine explizite Trennung ein:

- `MCP Servers` als Management-/Control-Plane fuer Catalog-Discovery, Inventory, Install, Enable, Disable und Status
- normale Tool-Plane fuer entdeckte MCP-Tools, sobald ein Server ready ist

MCP bleibt damit ein Adapter auf die bestehende Tool-Schicht:

- MCP-Tools werden als normale `ToolSpec`-/`ToolExecutor`-Eintraege im `ToolRegistry` gespiegelt
- `ToolPolicy`, `ToolOrchestrator` und `ToolLoopEngine` bleiben fuer MCP-Tools dieselben wie fuer native Tools
- es gibt keine zweite MCP-spezifische Plan- oder Execution-Welt

Der sichtbare UI-Split ist deshalb bewusst:

- `Tools`
- `MCP Servers`
