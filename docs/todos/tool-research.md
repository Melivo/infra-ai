# Tool Research and Implementation

## Goal

`infra-ai` soll spaeter eine kleine, sinnvolle Auswahl an guten und gaengigen Tools unterstuetzen.

Dieses Dokument dient dazu, die Recherche und Auswahl dieser Tools vorzubereiten, bevor sie implementiert werden.

## Focus

Gesucht werden Tools, die:

- haeufig in AI-Workflows nuetzlich sind
- gut zur router-zentrierten Architektur von `infra-ai` passen
- sich kontrolliert und sicher ausfuehren lassen
- den Tool Execution Layer sinnvoll erweitern

## Initial Categories

Moegliche erste Tool-Kategorien:

- Filesystem-Tools
- Git-Tools
- HTTP-Tools
- Shell-nahe Tools nur sehr vorsichtig
- spaeter MCP-basierte Tools

## Selection Criteria

Ein Tool sollte bevorzugt werden, wenn es:

- klaren praktischen Nutzen hat
- klein und reviewbar implementierbar ist
- ein begrenztes Risikoprofil hat
- gut in `ToolSpec`, `ToolPolicy` und `ToolOrchestrator` passt
- ohne Frontend- oder Provider-Sonderlogik nutzbar bleibt

## Likely Early Candidates

Realistische erste Kandidaten:

- `filesystem.read`
- `filesystem.write`
- `git.status`
- `git.diff`
- `http.fetch`

Bewusst spaeter oder vorsichtiger:

- Shell-Ausfuehrung
- breit offene Netzwerktools
- Tools mit hohem Seiteneffekt-Risiko

## TODO

- [ ] Kriterien fuer "gute Standardtools" festhalten
- [ ] Bestehende Tool-Patterns aus anderen AI-Systemen vergleichen
- [ ] Kleine erste Toolliste fuer Phase 1 definieren
- [ ] Risiko pro Tool grob einstufen
- [ ] Pruefen, welche Tools `enabled_by_default` sein duerfen
- [ ] Priorisierte Implementierungsreihenfolge festlegen
- [ ] Pro Tool eine kleine Spezifikation fuer `ToolSpec` und erwartetes `ToolResult` skizzieren
- [ ] Sicherheitsgrenzen pro Tool-Kategorie festhalten
- [ ] Entscheiden, welche Tools erst nach MCP kommen sollen

## Open Questions

- Welche Tools sind im Alltag wirklich haeufig genug, um frueh aufgenommen zu werden?
- Welche Tools sollten strikt lokal bleiben?
- Welche Tools brauchen spaeter zusaetzliche Policy-Regeln?
- Welche Tools sind fuer Phase 1 zu riskant oder zu breit?

## Status

Planning only.

Noch keine Tool-Recherche abgeschlossen.
Noch keine konkrete Tool-Implementierung aus diesem Dokument umgesetzt.
