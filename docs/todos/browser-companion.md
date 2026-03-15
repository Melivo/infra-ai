# Browser Companion TODO

## 1. Ziel der Browser Companion Extension

Die Browser Companion Extension soll Browser-Kontext mit dem lokalen `infra-ai` Router verbinden, ohne selbst AI- oder Provider-Logik zu enthalten.

Rolle der Extension:

- Browser-Kontext Adapter
- Session Bridge
- Request Forwarder

Nicht Aufgabe der Extension:

- keine direkte Kommunikation mit OpenAI, Gemini oder lokalen Modellen
- keine Modellwahl
- keine Providerwahl
- keine Routing-Logik
- keine Speicherung von API-Keys

Zielarchitektur:

```text
Browser
  -> Browser Extension
    -> localhost Bridge
      -> infra-ai Router
        -> local vLLM
        -> Gemini API
        -> OpenAI API
```

Der Router bleibt die zentrale AI-Plattform. Die Extension bleibt ein dünner Browser-Frontend-Adapter.

## 2. Architekturüberblick

Geplanter Datenfluss:

```text
Vivaldi / Chromium
  -> content script / browser UI
    -> extension background layer
      -> bridge communication
        -> http://localhost:8010
          -> infra-ai Router
```

Architekturprinzipien:

- Browser-seitige Logik bleibt klein.
- Router-seitige Logik bleibt zentral.
- Browser-Kontext wird nur gesammelt, strukturiert und an den Router übergeben.
- Die Extension liest Router-Capabilities statt Providerannahmen zu duplizieren.
- Session- oder Automationslogik soll langfristig routergesteuert bleiben.

Kommunikationsvarianten:

- HTTP gegen Router-Endpunkte
- optional spaeter WebSocket oder SSE fuer Streaming-nahe Flows

Fuer Phase 1 reicht eine einfache lokale Bridge gegen `http://localhost:8010`.

## 3. Repo Struktur Vorschlag

Moegliche spaetere Struktur:

```text
infra-ai-browser-companion/
  manifest.json
  background.js
  content.js
  bridge.js
  options.html
  options.js
  icons/
```

Optionaler Platz im infra-ai Repo:

```text
docs/
  todos/
    browser-companion.md

browser-companion/
  manifest.json
  background.js
  content.js
  bridge.js
```

Planungsgrundsatz:

- Dokumentation zuerst
- spaeter ein klar abgegrenztes Verzeichnis fuer die Extension
- keine Vermischung mit Router-Code

## 4. Router API Anforderungen

Die Extension soll nur mit Router-Endpunkten sprechen.

Minimal sinnvoll:

- `GET /healthz`
- `GET /v1/router/capabilities`
- `GET /v1/models`
- `POST /v1/chat/completions`

Moegliche spaetere Companion-spezifische Anforderungen:

- Browser-Kontext als strukturierter Payload im bestehenden Chat-Request
- optional spaeter dedizierte Companion-Endpunkte, falls wirklich noetig
- Streaming-kompatibler Response-Pfad

Wichtige Router-Regeln fuer die Extension:

- der Router definiert Routing-Modi
- der Router definiert sichtbare Modelle
- der Router normalisiert Fehler
- der Router kontrolliert Timeouts
- die Extension zeigt diese Informationen nur an

TODO:

- [ ] Pruefen, ob bestehende Router-Endpunkte fuer einen Minimal-Companion ausreichen
- [ ] Definieren, wie Browser-Kontext im Request-Payload repraesentiert werden soll
- [ ] Festlegen, ob Phase 1 nur `POST /v1/chat/completions` nutzt
- [ ] Pruefen, ob spaeter ein Companion-spezifischer Router-Namespace sinnvoll ist
- [ ] Festlegen, wie Streaming ueber die Router-Schnittstelle genutzt werden soll

## 5. Extension Komponenten

### `manifest.json`

Zweck:

- definiert Permissions
- registriert Background-Skripte
- registriert Content-Skripte
- beschreibt Extension-Metadaten

TODO:

- [ ] Manifest-Version festlegen
- [ ] minimale Permissions definieren
- [ ] Host-Permissions fuer `http://localhost:8010` pruefen
- [ ] Vivaldi / Chromium Kompatibilitaet pruefen

Offene Fragen:

- Welche Permissions sind wirklich minimal noetig?
- Wird spaeter `activeTab` genuegen oder werden breitere Host-Rechte benoetigt?

### `background.js`

Zweck:

- zentrale Extension-Orchestrierung
- Bridge zwischen UI, Content-Script und Router
- Session- oder Tab-bezogene Steuerung

TODO:

- [ ] Background-Lifecycle fuer Minimal-Companion definieren
- [ ] Health-Check gegen Router aus dem Background pruefen
- [ ] Request-Forwarding zentral im Background verankern
- [ ] Fehleranzeige fuer Router nicht erreichbar definieren

Offene Fragen:

- Soll der Background allein mit dem Router sprechen?
- Wie werden mehrere Tabs oder Sessions spaeter unterschieden?

### `content.js`

Zweck:

- liest Seitenkontext aus dem Browser
- extrahiert spaeter DOM-Inhalt, Titel, URL oder Selektion
- sendet strukturierte Kontextdaten an den Background

TODO:

- [ ] minimales Kontextmodell fuer Phase 1 definieren
- [ ] URL, Titel und grobe Seitenmetadaten extrahieren
- [ ] spaeter DOM-Extraction klar begrenzen
- [ ] keine sensiblen Inhalte ungefiltert weiterreichen

Offene Fragen:

- Wie viel Seiteninhalt darf standardmaessig ueberhaupt gesendet werden?
- Braucht es explizite Nutzerfreigabe pro Seite oder pro Aktion?

### `bridge.js`

Zweck:

- kapselt lokale Kommunikation mit dem Router
- abstrahiert HTTP oder spaeter Streaming-Verbindungen
- haelt Extension-Komponenten frei von Router-Details im UI-Code

TODO:

- [ ] minimalen Router-Client fuer Health-Check definieren
- [ ] minimalen Router-Client fuer Chat-Requests definieren
- [ ] Fehleroberflaeche des Routers sauber an UI weitergeben
- [ ] spaeter Streaming-Unterstuetzung planen

Offene Fragen:

- Bleibt HTTP fuer Phase 1 ausreichend?
- Soll spaeter SSE oder WebSocket in der Bridge gekapselt werden?

## 6. Sicherheitsueberlegungen

Grundsaetze:

- keine API-Keys in der Extension
- keine direkte Providerkommunikation
- keine ungepruefte Weitergabe sensibler Browserinhalte
- localhost-Kommunikation nur mit dem lokalen Router

Zu beachten:

- Seitenkontext kann sensible Daten enthalten
- Content-Scripts koennen auf viele DOM-Inhalte zugreifen
- Prompt Injection oder manipulierte Seitentexte duerfen nicht blind uebernommen werden
- Browser- und Tab-Kontext sollte moeglichst explizit und minimiert uebertragen werden

TODO:

- [ ] minimales Berechtigungsmodell fuer die Extension definieren
- [ ] Regeln fuer Datensparsamkeit bei Kontextuebertragung definieren
- [ ] Nutzerfreigabe fuer Seitentext oder Selektion planen
- [ ] lokalen Router-Trust-Mechanismus dokumentieren
- [ ] Logging-Regeln fuer Extension ohne sensible Inhalte definieren
- [ ] moegliche Prompt-Injection-Risiken fuer Browser-Kontext dokumentieren

Offene Fragen:

- Welche Daten duerfen ohne weitere Bestaetigung an den Router gehen?
- Wie soll mit Login-Seiten, privaten Tabs oder internen Dashboards umgegangen werden?

## 7. Entwicklungsphasen

### Phase 0 – Architekturdefinition

Ziel:

Saubere Trennung zwischen Browser Extension, Bridge und Router festlegen.

TODO:

- [ ] Verantwortlichkeiten zwischen Extension und Router festschreiben
- [ ] Kommunikationsmodell HTTP vs. spaeter Streaming dokumentieren
- [ ] minimales Kontextschema fuer Browserdaten definieren
- [ ] Sicherheits- und Permission-Ansatz festhalten
- [ ] Vivaldi / Chromium Installationspfad fuer Unpacked Extension dokumentieren

Offene Fragen:

- Braucht es eine dedizierte Companion-API im Router oder reicht der bestehende Contract?
- Welche Browserdaten sind fuer Phase 1 wirklich notwendig?

### Phase 1 – Minimal Companion

Ziel:

Kleinste lauffaehige Companion-Extension mit Router-Health-Check, einfacher Bridge und einfachem Kontextversand.

TODO:

- [ ] `manifest.json` minimal planen
- [ ] `background.js` als zentrale Router-Bridge planen
- [ ] `bridge.js` fuer `GET /healthz` definieren
- [ ] Browser-Kontext-Minimum definieren: URL, Titel, Tab-ID
- [ ] einfache Aktion planen, die Kontext an den Router sendet
- [ ] Fehlerfall fuer Router offline definieren

Offene Fragen:

- Soll Phase 1 schon ein sichtbares UI haben oder nur eine technische Bridge?
- Wie wird der Browser-Kontext im Request konkret eingebettet?

### Phase 2 – Kontextintegration

Ziel:

Seitenkontext nutzbarer machen, ohne Browserlogik in AI-Logik ausarten zu lassen.

TODO:

- [ ] DOM-Extraction-Grenzen definieren
- [ ] Seitenauswahl oder markierten Text als Kontextmodell planen
- [ ] Router-seitige Darstellung von Browser-Kontext vorbereiten
- [ ] Kontextquellen priorisieren: URL, Titel, Selection, DOM
- [ ] explizite Nutzeraktionen fuer Kontextuebertragung planen

Offene Fragen:

- Soll kompletter Seitentext jemals standardmaessig gesendet werden?
- Wie granular soll Nutzerkontrolle ueber gesendeten Kontext sein?

### Phase 3 – Streaming

Ziel:

Streaming-Antworten des Routers im Browser nutzbar machen.

TODO:

- [ ] Streaming-Transport fuer Extension-Bridge festlegen
- [ ] UI-Strategie fuer inkrementelle Antworten planen
- [ ] Fehler- und Reconnect-Verhalten fuer Streaming definieren
- [ ] lokale Router-Streaming-Grenzen dokumentieren

Offene Fragen:

- Reicht SSE fuer den Companion oder ist spaeter WebSocket sinnvoller?
- Wie wird Streaming in mehreren Tabs oder Sessions dargestellt?

### Phase 4 – MCP / Tools

Ziel:

Browser Companion als moegliche Oberflaeche fuer spaetere routergesteuerte Tools und MCP-Flows vorbereiten.

TODO:

- [ ] Browseraktion als moegliches Tool-Target konzeptionell beschreiben
- [ ] MCP-Bezug nur als routergesteuerte Schicht dokumentieren
- [ ] Rollenverteilung zwischen Companion und Router fuer Tool-Calls festlegen
- [ ] Sicherheitsgrenzen fuer Browser-Tools dokumentieren

Offene Fragen:

- Welche Browseraktionen duerfen spaeter tool-faehig werden?
- Wie werden Nutzerbestaetigungen fuer sensible Aktionen eingebaut?

### Phase 5 – Advanced Browser Automation

Ziel:

Langfristige, bewusst spaete Browser-Automationsideen dokumentieren, ohne sie in fruehe Phasen zu ziehen.

TODO:

- [ ] Automationsgrenzen und Sicherheitsmodell definieren
- [ ] Session-bezogene Browseraktionen planen
- [ ] navigationsbezogene Router-Flows beschreiben
- [ ] Abgrenzung zwischen Companion und vollwertigem Browser-Agent festhalten

Offene Fragen:

- Wann wird ein Companion zu einem Agenten und gehoert dann nicht mehr in dieselbe Komponente?
- Welche Automationsfaelle sind lokal verantwortbar, welche nicht?

## Future Ideas

- [ ] Multi Browser Support planen
- [ ] Firefox Support bewerten
- [ ] Context Menus fuer schnelle Kontextuebertragung planen
- [ ] Page Selection Tools konzipieren
- [ ] Prompt Injection Detection als Schutzschicht evaluieren
- [ ] Tab-Gruppen oder Session-Kontext spaeter untersuchen
- [ ] Lesemodus- oder vereinfachte DOM-Extraktion pruefen
- [ ] ChatGPT Session Relay nur als spaete, bewusst optionale Erweiterung betrachten
- [ ] lokale Browser-Kontext-Caches nur mit klarer Privacy-Policy untersuchen
