# Tool Execution Layer

## Einordnung

Der Tool Execution Layer ist die naechste sinnvolle Architekturphase nach dem stabilisierten Router-Core.

Der aktuelle Router kann Requests validieren, routen, Fehler normalisieren und Providerzugriffe kontrollieren. Der naechste logische Schritt ist eine saubere, router-zentrierte Ausfuehrung von Tools, ohne Frontends aufzublaehen oder spaetere Agentenlogik vorwegzunehmen.

Wichtig:

- der Router bleibt die zentrale Plattform
- Frontends bleiben duenne Clients
- Tool-Ausfuehrung gehoert nicht ins Frontend
- Tool-Ausfuehrung darf den Router nicht entkernen

## Architekturziele

- Tools als klar definierte Router-Komponente planen
- Tool-Aufrufe ueber einen stabilen internen Vertrag beschreiben
- Sicherheitsgrenzen frueh definieren
- spaetere Agenten auf einen bestehenden Tool Layer aufsetzen lassen
- MCP spaeter als Adapter-Modell integrieren statt als separates Parallelsystem
- die erste Phase bewusst klein und kontrollierbar halten

## Nicht-Ziele fuer Phase 1

- keine Agent-Orchestrierung
- keine autonome Multi-Step-Planung
- keine freie Shell-Ausfuehrung ohne harte Grenzen
- keine Frontend-seitige Tool-Logik
- keine produktiven Workflow-Engines
- keine breite MCP-Implementierung
- keine kundenspezifischen Tool-Pipelines

## Zielarchitektur

```text
Frontend
  -> Router API
    -> Route / Policy Layer
      -> Model Invocation
        -> Tool Orchestrator
          -> Tool Executor
            -> Filesystem Tools
            -> Git Tools
            -> HTTP Tools
            -> MCP Adapters
        -> Model Finalization
  -> Response
```

Oder aus Sicht eines spaeteren agentischen Flows:

```text
User
  -> Router
    -> Model
      -> Tool Call
        -> Tool Executor
          -> Tool Result
    -> Final Response
```

Der Router bleibt dabei die einzige Schicht, die Modellantworten, Tool Policies, Tool-Aufrufe und Tool-Ergebnisse zusammenfuehrt.

## Tool Iteration Loop

Fuer die spaetere Laufzeitsequenz sollte der Tool Layer bewusst kontrolliert bleiben.

Vorgeschlagener Ablauf:

```text
User Request
  -> Router
    -> Model Response
      -> ToolCall detected
        -> Policy check
          -> Executor run
            -> ToolResult
              -> ToolResult injected into conversation / context
                -> Model continues
                  -> Final Response
```

Wichtige Phase-1-Regel:

- Phase 1 sollte einen harten Grenzwert fuer Tool-Schritte haben
- vorgeschlagen: `max_tool_steps` als kleine feste Obergrenze
- keine offenen oder unendlichen Tool-Loops
- kein autonomes Iterieren ohne klaren Stop-Zustand

Phase 1 ist damit bewusst klein:

- ein Modell darf Tool-Aufrufe nur vorschlagen
- der Router erkennt und prueft sie
- nur erlaubte Tool-Aufrufe werden ausgefuehrt
- nach einer kleinen festen Anzahl von Tool-Schritten ist Schluss

Das dient der Kontrollierbarkeit, Fehlerbegrenzung und einfacheren Beobachtbarkeit.

## Empfohlene Kernkomponenten

### Tool Registry

Zweck:

- bekannte Tools registrieren
- Tool-Namen eindeutig verwalten
- Tool-Metadaten und Input/Output-Schemas halten

### Tool Policy

Zweck:

- entscheiden, welche Tools ueberhaupt erlaubt sind
- Deny-by-default durchsetzen
- Workspace-, Netzwerk- und Sicherheitsgrenzen abbilden

### Tool Orchestrator

Zweck:

- Tool-Aufrufe innerhalb des Routers koordinieren
- Validierung, Policy-Pruefung und Ausfuehrung verbinden
- mehrere Tool-Schritte kontrolliert zusammensetzen
- Stop-Bedingungen und `max_tool_steps` durchsetzen

### Tool Executor

Zweck:

- einen konkreten Tool-Aufruf ausfuehren
- Timeouts, Fehler und Ergebnisform vereinheitlichen
- keine Modelllogik enthalten

### Tool Adapters

Zweck:

- konkrete Integrationen kapseln
- Dateisystem, Git, HTTP oder spaeter MCP sauber anbinden
- Adapter austauschbar halten, ohne den Router-Vertrag zu veraendern

## Vorgeschlagene interne Struktur unter `router/tools/`

Nur als Vorschlag, nicht als umgesetzt:

```text
router/
  tools/
    registry.py
    policies.py
    orchestrator.py
    executor.py
    schemas.py
    adapters/
      filesystem.py
      git.py
      http.py
      mcp.py
```

Rollen:

- `registry.py`: bekannte Tools und ToolSpec-Definitionen
- `policies.py`: Allowlist-, Workspace- und Sicherheitsregeln
- `orchestrator.py`: Ablauf zwischen Registry, Policy und Executor
- `executor.py`: standardisierte Tool-Ausfuehrung
- `schemas.py`: gemeinsame interne Tool-Vertraege
- `adapters/`: konkrete Tool-Integrationen

## Minimaler Vertragsentwurf

### ToolSpec

Beschreibt ein registriertes Tool.

Beispielhafte Felder:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `capabilities`
- `requires_confirmation`
- `timeout_s`
- `enabled`

### ToolCall

Beschreibt einen einzelnen Tool-Aufruf.

Beispielhafte Felder:

- `tool_name`
- `arguments`
- `call_id`
- `requested_by`
- `context`

### ToolResult

Beschreibt das standardisierte Ergebnis.

Beispielhafte Felder:

- `call_id`
- `status`
- `output`
- `error`
- `duration_ms`

### ToolContext

Beschreibt den kontrollierten Ausfuehrungskontext.

Beispielhafte Felder:

- `workspace_root`
- `allowed_paths`
- `http_allowlist`
- `user_intent`
- `session_id`
- `tool_step`
- `max_tool_steps`

## Router Capabilities fuer Tools

Tool-Verfuegbarkeit sollte spaeter ueber den bestehenden Router-Mechanismus sichtbar gemacht werden, nicht ueber Frontend-spezifische Logik.

Die bevorzugte Richtung ist:

- Tool-Verfuegbarkeit wird ueber `GET /v1/router/capabilities` sichtbar
- Frontends lesen diese Informationen nur aus
- Frontends implementieren keine eigene Tool-Allowlist
- Frontends entscheiden nicht selbst, welche Tools wirklich ausfuehrbar sind

Moegliche spaetere Richtung, nur als Vorschlag:

```json
{
  "tools": [
    "filesystem.read",
    "git.status",
    "http.fetch"
  ]
}
```

Das ist ausdruecklich noch nicht implementiert.

Die Absicht ist:

- der Router bleibt Quelle der Wahrheit fuer Tool-Verfuegbarkeit
- Frontends bleiben duenne Clients
- spaetere UIs koennen Tool-Support anzeigen, ohne Tool-Logik zu duplizieren

## Sicherheitsprinzipien

- deny by default
- Schema-Validierung fuer Tool-Inputs
- Timeouts pro Tool-Aufruf
- Workspace-Grenzen fuer Dateisystemzugriffe
- HTTP-Allowlist fuer Netzwerkanfragen
- Logging ohne Secrets oder sensible Inhalte
- keine implizite Freigabe gefaehrlicher Operationen
- klare Trennung zwischen Lese- und Schreibwerkzeugen
- feste Obergrenzen fuer Tool-Iterationen

Phase 1 sollte nur kontrollierte, nachvollziehbare Tools erlauben.

## Kompatibilitaet mit spaeteren Agents

Agents sollen spaeter planen und orchestrieren koennen.

Die eigentliche Tool-Ausfuehrung bleibt trotzdem im Router.

Das bedeutet:

- Agents duerfen nicht zu einem separaten Ausfuehrungssystem werden
- Agents planen Tool-Nutzung, aber der Router validiert und fuehrt aus
- Tool Policies bleiben backend-seitig zentral
- Iterationsgrenzen und Stop-Regeln bleiben backend-seitig zentral
- Frontends bleiben auch im agentischen Fall duenne Clients

## Kompatibilitaet mit MCP

MCP sollte spaeter als Adapter-Modell verstanden werden.

Das bedeutet:

- MCP ist keine parallele Architektur neben dem Tool Layer
- MCP-Server werden ueber Adapter in dieselbe Tool-Ausfuehrung eingebunden
- der Router behaelt dieselben Sicherheits-, Timeout- und Logging-Regeln
- MCP erweitert die Tool-Flaeche, ersetzt aber nicht Registry, Policy oder Executor

## Schlanke Phase-1-Empfehlung

Sinnvolle erste Tools:

- `filesystem.read`
- `filesystem.write`
- `git.status`
- `git.diff`
- `http.fetch`

Shell-Tools nur vorsichtig oder spaeter.

Begruendung:

- Dateisystem und Git sind fuer Entwicklungs- und Projektkontext naheliegend
- `http.fetch` ist fuer kontrollierte externe Datenzugriffe nuetzlich
- freie Shell-Ausfuehrung ist deutlich riskanter und sollte nicht der erste Schritt sein
- eine kleine feste Obergrenze fuer Tool-Schritte ist in Phase 1 realistisch und kontrollierbar

## To-do-Liste

- [ ] Tool-Layer-Ziele und Nicht-Ziele final festschreiben
- [ ] minimalen internen Tool-Vertrag definieren
- [ ] Entscheidung fuer zentrale Tool Registry dokumentieren
- [ ] Policy-Modell fuer Deny-by-default und Scope-Grenzen festlegen
- [ ] Timeouts und Fehlervertrag fuer Tool-Aufrufe definieren
- [ ] Tool-Iteration-Loop und `max_tool_steps` fuer Phase 1 festlegen
- [ ] ersten Satz sicherer Phase-1-Tools festlegen
- [ ] Trennung zwischen Registry, Policy, Orchestrator und Executor dokumentieren
- [ ] Tool-Verfuegbarkeit ueber `GET /v1/router/capabilities` einordnen
- [ ] MCP als Adapter-Modell in die Architektur einordnen
- [ ] Agent-Kompatibilitaet dokumentieren, ohne Agenten jetzt zu bauen
- [ ] pruefen, welche Teile public-repo-tauglich und welche privat bleiben muessen

## Offene Architekturentscheidungen / offene Fragen

- Wie stark soll ein Modell Tool-Aufrufe direkt anstossen duerfen?
- Wo liegt die Grenze zwischen Tool Orchestrator und spaeterem Agent Layer?
- Wie klein soll `max_tool_steps` in Phase 1 konkret sein?
- Soll `filesystem.write` in Phase 1 schon erlaubt sein oder erst nach rein lesenden Tools?
- Wie fein soll die HTTP-Allowlist sein?
- Wie werden Nutzerbestaetigungen fuer riskantere Tools spaeter eingebaut?
- Wie werden MCP-Adapter in dieselben Policies eingebunden?
- Wie detailliert sollen Tool-Capabilities spaeter im Router sichtbar sein?
- Wie viel Tool-Kontext darf in Logs auftauchen, ohne sensible Inhalte preiszugeben?

## Akzeptanzkriterien fuer „Tool Layer Phase 1 geplant“

- die Rolle des Tool Layers im Router ist klar beschrieben
- die Kernkomponenten sind benannt und voneinander abgegrenzt
- ein minimaler interner Vertrag fuer Tool-Aufrufe ist festgehalten
- Sicherheitsprinzipien sind dokumentiert
- Phase-1-Tools sind bewusst klein und realistisch ausgewaehlt
- die spaetere Kompatibilitaet mit Agents ist beschrieben, ohne Agenten vorzuziehen
- die spaetere Kompatibilitaet mit MCP ist als Adapter-Modell beschrieben
- der Tool-Iteration-Loop ist beschrieben
- eine feste Phase-1-Grenze gegen Endlosschleifen ist benannt
- die spaetere Sichtbarkeit von Tools ueber Router-Capabilities ist beschrieben
- es gibt eine konkrete To-do-Liste fuer die naechste Architekturphase
