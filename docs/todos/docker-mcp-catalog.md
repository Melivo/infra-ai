# Docker MCP Catalog TODO

## Ziel

Ich moechte spaeter den Docker MCP Catalog fuer `infra-ai` einrichten bzw. den Zugang dazu vorbereiten.

Das Ziel ist, dass `infra-ai` kuenftig mit einem Docker-basierten MCP-Umfeld arbeiten kann, ohne die bestehende Router-Architektur aufzubrechen.

## Architekturgedanke

Die Anbindung soll spaeter sauber in die bestehende Struktur passen:

```text
Frontend
  -> infra-ai Router
    -> Tool Execution Layer
      -> MCP Adapter
        -> Docker MCP Catalog / MCP Toolkit / MCP Gateway
```

Wichtig:

- der Router bleibt die zentrale Plattform
- Frontends sprechen weiterhin nur mit dem Router
- keine direkte MCP-Logik in Frontends
- keine Secrets im Public Repo

## Was gewuenscht ist

- Zugang zum Docker MCP Catalog vorbereiten
- pruefen, wie MCP-Server oder MCP-Tools spaeter ueber Docker bereitgestellt werden koennen
- dokumentieren, wie sich das mit dem Router-Ansatz von `infra-ai` verbinden laesst

## Noch nicht Teil dieses Schritts

- keine Implementierung
- keine Docker-MCP-Integration im Code
- keine Tool-Ausfuehrung
- keine Agentenlogik
- keine Workflow-Automation

## Offene Punkte

- [ ] Pruefen, wie Docker MCP Catalog technisch fuer `infra-ai` angebunden werden soll
- [ ] Definieren, welche Rolle der Router bei MCP-Zugriff und Tool-Freigabe uebernimmt
- [ ] Klaeren, welche Teile public-repo-tauglich sind und welche privat bleiben muessen
- [ ] Dokumentieren, wie spaetere MCP-Server ueber Docker gestartet und verwaltet werden koennen
- [ ] Festlegen, wie sich MCP sauber in die bestehende Router- und Tool-Architektur einfuegt

## Status

Status:

Idea / Planning

Dieses Dokument dient nur als Platzhalter und Planung fuer eine spaetere Docker-MCP-Catalog-Anbindung.
