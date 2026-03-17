# AGENTS

Diese Datei definiert die Standard-Arbeitskonvention fuer Codex in `Melivo/infra-ai`.

## Prioritaetsreihenfolge

Wenn diese Dokumente vorhanden sind, gelten sie in dieser Reihenfolge:

1. `docs/architecture-rules.md`
2. `docs/architecture.md`
3. `AGENTS.md`
4. aufgabenspezifische Prompt-Dateien unter `docs/prompts/`

Bei Konflikten haben die Architekturregeln Vorrang.

## Standard-Arbeitsmodus

- Standard: direkt ohne Sub-Agents arbeiten.
- Wenn der Nutzer `nutze deine agenten`, `nutze die 3 agenten` oder etwas Gleichwertiges sagt, nutze dieses Standard-Setup mit 3 Rollen:
  - Architecture / Implementation Agent
  - QA / Invariants Agent
  - Docs / Prompt Hygiene Agent
- Verwende dieselbe 3-Rollen-Struktur wieder, sofern der Nutzer keine andere Aufteilung verlangt.
- Erfinde keine weiteren Agent-Rollen, sofern es dafuer keinen starken, aufgabenspezifischen Grund gibt.

## Verantwortlichkeiten der Agents

### 1. Architecture / Implementation Agent

- verantwortet Codeaenderungen
- bewahrt die architektonischen Invarianten des Routers
- arbeitet hauptsaechlich in:
  - `router/conversation.py`
  - `router/tool_loop.py`
  - `router/provider_output/*`
  - relevanten Tests und Doku

Muss durchsetzen:

- Turn-First Core
- `ExecutionStep` als Orchestrierungseinheit
- `ExecutionPlan` als First-Class State
- Isolation der Provider-Grenze
- kein `Normalized*`-Leakage in den Core

### 2. QA / Invariants Agent

- prueft auf Verstoesse gegen die Architekturregeln
- fokussiert auf versteckte Kopplung, Determinismus, Boundary-Regressionen und fehlende Tests

Muss explizit pruefen:

- keine providerspezifische Logik im Router-Core
- keine ad-hoc Rekonstruktion des Plans waehrend der Ausfuehrung
- keine Wiedereinfuehrung von `NormalizedMessage` / `NormalizedGeneration` als Core-Modelle
- deterministische, begrenzte Tool-Ausfuehrung
- erhaltene Kompatibilitaet an HTTP-/Provider-Grenzen

### 3. Docs / Prompt Hygiene Agent

- aktualisiert Doku, wenn sich durch die Implementierung Formulierungen oder Architekturerklaerungen aendern
- haelt Prompt-Templates an die aktuelle Repo-Praxis angepasst

Muss explizit pruefen:

- Architektur-Dokumente passen noch zur Implementierungsrichtung
- Prompt-Templates unter `docs/prompts/` bleiben aktuell
- fehlende Prompt-Dateien werden explizit benannt

## Repo-spezifische Arbeitsregeln

- Behandle `docs/architecture-rules.md` als nicht verhandelbar.
- Bevorzuge kleine, explizite, deterministische Aenderungen.
- Halte providerspezifisches Parsing innerhalb von `router/provider_output/*`.
- Halte `ToolLoopEngine` provider-agnostisch.
- Halte `Normalized*`-Modelle an den Boundaries.
- Bewahre das aktuelle V1-Verhalten, sofern die Aufgabe es nicht explizit aendert.
- Fuehre keine Parallelisierung, kein MCP, kein RAG und kein Agent-Framework-Verhalten ein, sofern es nicht explizit verlangt wird.
- Nutze gezielte Tests fuer geaendertes Verhalten.

## Test-Workflow

- Bevorzuge Red/Green-TDD fuer Verhaltensaenderungen, Bugfixes, Router-Core-Refactors, Parser-Aenderungen und Tool-Loop-Invarianten.
- Wenn praktikabel, schreibe oder aktualisiere zuerst den kleinsten Test, der das gewuenschte Verhalten oder die Regression abbildet, bestaetige den Red-Zustand und implementiere dann die kleinste Aenderung bis Green.
- Wenn Red/Green-TDD fuer die konkrete Aufgabe kein guter Fit ist, sage das kurz und nutze stattdessen die schmalste sinnvolle Test- und Verifikationsstrategie.

## Push-Policy

- In zukuenftigen Sessions gilt: Nach Abschluss jeder angeforderten Aenderung sofort committen und direkt nach `origin/main` pushen, sofern der Nutzer nicht ausdruecklich etwas anderes sagt.
- Warte nach Abschluss einer Aenderung nicht auf eine separate `push`-Anweisung.
- Halte Commit-Messages praezise und eng auf die Aenderung begrenzt.
