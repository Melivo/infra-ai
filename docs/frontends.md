# Frontends

`infra-ai` ist keine reine Terminal-Anwendung. Der Router ist die zentrale Chat- und Inference-Plattform, auf die mehrere Frontends aufsetzen koennen.

## Zielbild

```text
Terminal CLI ----\
                  -> infra-ai Router -> Provider Routing
Code OSS IDE ----/                   -> local_vllm
                                       -> gemini_fallback
                                       -> openai_responses
```

## Grundsaetze

- Frontends sprechen nur mit dem Router.
- Frontends enthalten keine Provider-Logik.
- Frontends enthalten keine Modell-Routing-Logik.
- Streaming wird ueber den Router gedacht, nicht direkt ueber Provider-spezifische Clients.
- Der Router-Vertrag ist fuer mehrere Clients gemeinsam nutzbar.

## Aktueller Stand

- `cli/` ist das aktuelle Referenz-Frontend.
- `GET /v1/router/capabilities` ist der Introspection-Pfad fuer Frontends.
- `POST /v1/chat/completions` ist der gemeinsame Chat-Pfad fuer Frontends.
- Routing-Modi wie `auto`, `local`, `reasoning` und `heavy` werden vom Router ausgewertet.

## Geplanter spaeterer IDE-Chat

Eine spaetere Integration in Code OSS soll:

- denselben Router-Endpunkt verwenden wie die CLI
- denselben Routing-Vertrag verwenden wie die CLI
- dieselben Capabilities aus dem Router lesen koennen
- kein eigener Modell- oder Providerpfad sein

Nicht Teil dieses Schritts:

- keine IDE-Extension
- keine Tool-Integration
- keine Agentenlogik
- keine MCP-Integration
- keine Realtime- oder Voice-Oberflaeche

## Public und Private

Public repo-tauglich:

- Frontend-Architekturdoku
- Referenz-CLI
- Router-Capabilities ohne Secrets

Privat bleiben muessen:

- echte API-Keys
- lokale `.env`-Dateien
- proprietaere Prompts
- sensible Projekt- oder Kundendaten
