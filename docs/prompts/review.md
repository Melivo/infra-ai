# Review

Nutze diese Vorlage, wenn du Code in `infra-ai` pruefst.

Bevor du reviewst, lies:

- `docs/architecture.md`
- `docs/architecture-rules.md`
- die geaenderten Dateien
- die relevanten Tests

Behandle die Architekturregeln als bindende Review-Kriterien.

## Review-Prioritaeten

Priorisiere Findings in dieser Reihenfolge:

1. Korrektheitsfehler und Regressionen
2. Verstoesse gegen Architekturregeln
3. versteckte Kopplung oder Boundary-Leakage
4. Risiken fuer Determinismus und begrenzte Ausfuehrung
5. fehlende oder zu schwache Tests
6. Doku-Drift

## Repo-spezifische Checks

Pruefe explizit:

- keine providerspezifische Logik im Router-Core
- keine ad-hoc Rekonstruktion des Plans waehrend der Ausfuehrung
- keine falsche Explizitheit, bei der deklarierte Struktur weiterhin nur in Tool-Call-Transportmetadaten lebt
- keine Wiedereinfuehrung von `NormalizedMessage` oder `NormalizedGeneration` als Core-Modelle
- keine Umgehung von `ExecutionStep` oder `ExecutionPlan`
- kein String-Parsing im Core dort, wo strukturierte Daten verwendet werden muessen
- kein Verlust deterministischer, begrenzter Tool-Ausfuehrung
- kein Kompatibilitaetsbruch an HTTP-/Provider-Grenzen durch interne Refactors
- bei Verhaltensaenderungen: ob ein gezielter Test vorhanden ist, der vor der Implementierung sinnvoll rot haette werden koennen
- fehlende Regressionstests dort markieren, wo Red/Green-TDD praktikabel gewesen waere

## Ausgabeformat

Findings zuerst, nach Schweregrad sortiert.

Zu jedem Finding gehoeren:

- Schweregrad
- Dateireferenz
- das konkrete Problem
- warum es in dieser Architektur relevant ist

Wenn es keine Findings gibt, sage exakt:

`no findings`

Danach optional:

- verbleibende Risiken
- fehlende Tests
- kleine Anschlussarbeiten

## Review-Stil

- Sei direkt und technisch.
- Bevorzuge konkrete Evidenz vor Spekulation.
- Schlage keine grossen Rewrites vor, solange das aktuelle Design die Regeln nicht verletzt.
- Halte Zusammenfassungen nach den Findings kurz.
