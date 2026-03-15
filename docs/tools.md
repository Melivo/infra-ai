# Tools

Der Tool Execution Layer von `infra-ai` ist router-zentriert aufgebaut.

Der Router bleibt die kontrollierende Instanz. Tools sind weder Frontend-Logik noch Provider-Logik. Ein Tool wird ueber einen klaren internen Vertrag beschrieben, registriert und spaeter kontrolliert ausgefuehrt.

## Aktueller Stand

Aktuell existieren die grundlegenden Bausteine:

- `ToolSpec`, `ToolCall`, `ToolResult`, `ToolContext`, `ToolExecutor` in `router/tools/types.py`
- `ToolRegistry` in `router/tools/registry.py`
- `ToolPolicy` in `router/tools/policy.py`
- `ToolOrchestrator` in `router/tools/orchestrator.py`

Der Layer ist damit vorbereitet, aber noch nicht in den Router-Request-Flow integriert.

Aktuell gibt es einen ersten minimalen Integrationspfad ueber `POST /v1/chat/completions` mit einem expliziten `tool_call`-Feld. Dieser Pfad ist bewusst klein gehalten und dient nur dazu, die bestehende Tool-Pipeline kontrolliert ueber den Router nutzbar zu machen.

## Grundmodell

```text
ToolCall
-> ToolOrchestrator
-> ToolRegistry
-> ToolPolicy
-> ToolExecutor
```

Die Rollen sind bewusst getrennt:

- `ToolSpec` beschreibt Name, Beschreibung, Eingabeschema, Risk-Level und Capabilities eines Tools.
- `ToolExecutor` kapselt die eigentliche Ausfuehrung.
- `ToolRegistry` verwaltet die Zuordnung von Toolnamen zu `ToolSpec` und `ToolExecutor`.
- `ToolPolicy` entscheidet, ob ein Tool im aktuellen Kontext ausgefuehrt werden darf.
- `ToolOrchestrator` fuehrt Lookup, Policy-Check und Executor-Aufruf zusammen.

## Wie ein Tool aufgebaut ist

Ein Tool besteht im Kern aus drei Teilen:

1. einer `ToolSpec`
2. einem `ToolExecutor`
3. der Registrierung in der `ToolRegistry`

Die Tool-Implementierung selbst bleibt bewusst von Router-Endpunkten, Provider-Logik und Frontends entkoppelt.

## Minimaler Ablauf

Der aktuelle Zielablauf fuer einen normalisierten Tool-Aufruf ist:

1. Ein `ToolCall` liegt bereits in normalisierter Form vor.
2. Der `ToolOrchestrator` holt `ToolSpec` und `ToolExecutor` aus der `ToolRegistry`.
3. Die `ToolPolicy` prueft, ob das Tool im aktuellen `ToolContext` erlaubt ist.
4. Erst danach fuehrt der `ToolExecutor` den Aufruf aus.
5. Das Ergebnis wird als `ToolResult` zurueckgegeben.

## Was ein Tool aktuell noch nicht leisten muss

Bewusst noch nicht Teil des aktuellen Tool Layers sind:

- API-Exposure
- Tool-Erkennung aus Modellantworten
- Multi-Step-Orchestrierung
- Agent-Logik
- MCP-Integration
- JSON-Schema-Validierung
- Workspace-Pfadvalidierung
- HTTP-Allowlist-Logik

## Aktuelles Beispieltool

Der Router registriert aktuell nur ein minimales Beispieltool:

- `echo`

`echo` gibt die uebergebenen Argumente unveraendert als `ToolResult` zurueck. Das Tool dient nur als Infrastrukturtest fuer Registry, Policy, Orchestrator und den minimalen Router-Integrationspfad.

## Leitlinien fuer spaetere Tool-Implementierungen

- Tools bleiben klein und fokussiert.
- Tool-Ausfuehrung bleibt unter Router-Kontrolle.
- Keine stillen Fallbacks.
- Keine Tool-spezifische Logik in Frontends.
- Keine Vermischung von Registry, Policy und Ausfuehrung.
- Fehler und Sicherheitsregeln werden spaeter zentral ueber den Router und die Policy konsolidiert.
