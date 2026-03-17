# Implement Feature

Nutze diese Vorlage, wenn du bereit bist, ein Feature oder einen Refactor in `infra-ai` umzusetzen.

Bevor du irgendetwas tust, lies:

- `docs/architecture.md`
- `docs/architecture-rules.md`
- `AGENTS.md`
- alle direkt relevanten Implementierungsdateien

Behandle `docs/architecture-rules.md` als bindend.

## Auftrag

Implementiere die kleinste sichere Aenderung direkt im Code.

Diese Vorlage ist auf die Umsetzungsphase ausgerichtet:

- bleibe nicht in der Planung stehen,
- wenn der kleinste sichere Schritt noch nicht klar ist, stoppe und nutze zuerst `docs/prompts/plan_feature.md`,
- vergroessere den Scope nicht, sobald der sichere Schritt identifiziert ist,
- bevorzuge explizite Helper statt cleverer Logik,
- halte das Laufzeitverhalten deterministisch,
- bewahre das aktuelle V1-Verhalten, sofern die Aufgabe es nicht explizit aendert.

## Nicht verhandelbar

All das muss erhalten bleiben:

- `ConversationTurn` bleibt die primaere interne Repraesentation.
- `ExecutionStep` bleibt die Orchestrierungseinheit.
- `ExecutionPlan` bleibt First-Class State.
- Deklarierte Planstruktur muss expliziter interner State sein, nicht nur Transportmetadaten an Tool-Calls.
- Plan-State darf waehrend der Ausfuehrung nicht ad hoc aus Turns rekonstruiert werden.
- Providerspezifisches Parsing bleibt in `router/provider_output/*`.
- `ToolLoopEngine` bleibt provider-agnostisch.
- `NormalizedMessage` und `NormalizedGeneration` bleiben Boundary-only.
- Tool-Outputs nutzen strukturiertes `content_json`.
- Die Ausfuehrung bleibt deterministisch und durch `max_tool_steps` begrenzt.
- Kompatibilitaet wird an Boundaries behandelt, nicht im Core.

## Umsetzungsregeln

- Mache die kleinste saubere Aenderung, die die Aufgabe loest.
- Halte declaration-spec state, deklarierte Struktur, strategy-derived constraints und execution progress getrennt.
- Fuehre keine Parallelisierung, kein MCP, kein RAG und kein Agent-Framework-Verhalten ein, sofern nicht explizit verlangt.
- Fuehre keine providerspezifische Logik in die Router-Orchestrierung ein.
- Fuehre keine `Normalized*`-Modelle wieder in den Core ein.
- Bevorzuge kleine, explizite Helper und schmale Datenstrukturen.
- Aktualisiere Tests zusammen mit der Codeaenderung.
- Aktualisiere Doku nur dann, wenn sich die architektonische Aussage der Implementierung wirklich aendert.

## Erforderlicher Workflow

1. Pruefe die relevanten Dateien und identifiziere den aktuellen Ablauf.
2. Bevorzuge Red/Green-TDD, wenn die Aenderung Verhalten betrifft.
3. Schreibe oder aktualisiere zuerst den kleinsten gezielten Test fuer das gewuenschte Verhalten oder die Regression.
4. Bestaetige, dass dieser Test aus dem erwarteten Grund fehlschlaegt.
5. Implementiere danach die kleinste explizite Aenderung im Code.
6. Fuehre die relevantesten Tests fuer die beruehrten Flaechen aus.
7. Behebe nur die Fehler, die durch die Aenderung eingefuehrt oder sichtbar gemacht wurden.
8. Wenn Red/Green-TDD hier kein guter Fit ist, begruende das kurz und nutze den schmalsten sinnvollen Verifikationsweg.

## Review-Checks

Pruefe vor dem Abschluss:

- Bleibt `ConversationTurn` die Core-Repraesentation?
- Arbeitet die Orchestrierung weiterhin auf `ExecutionStep` und `ExecutionPlan`?
- Ist die Planwahrheit explizit statt aus Turns rekonstruiert?
- Ist deklarierte Struktur als expliziter Plan-/Declaration-State modelliert statt nur als Transportmetadaten?
- Bleibt providerspezifische Logik auf `router/provider_output/*` beschraenkt?
- Bleibt der Tool-Loop provider-agnostisch?
- Bleiben `Normalized*`-Modelle Boundary-only?
- Bleibt die Ausfuehrung deterministisch und begrenzt?
- Bleibt Rueckwaertskompatibilitaet an den Boundaries statt im Core?

## Erforderliche Ausgabeform

Halte den Abschlussbericht kurz und konkret.

Enthalten sein muessen:

- `Implemented`
- `Tests`
- `Risks`
- `Files`
- `Notes`

## Antwortstil

- Berichte ueber die konkrete Aenderung, nicht ueber einen Plan.
- Nenne die Dateien, die du geaendert hast.
- Nenne die Tests, die du ausgefuehrt hast, und ob sie bestanden haben.
- Benenne bewusste Einschraenkungen oder verbleibende Risiken.
