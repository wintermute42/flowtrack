# flowtrack – Feuer & Props live auf Resolume

Eine Kamera filmt den Artisten, flowtrack findet Feuer, LED-Poi oder farbige Bälle im Bild und steuert damit live Resolume Avenue (oder eigene Effekte direkt auf dem Beamer).

```
Kamera ──► Erkennung ──► Glättung ──► Kalibrierung ──┬─► OSC (x/y, 60×/s) ─────────► Resolume
                                                      ├─► WebSocket/REST (Parameter) ─► Resolume
                                                      ├─► Regeln (Clips starten …) ───► Resolume
                                                      └─► eigene Effekte ─► Beamer / Syphon ─► Resolume
```

## 1. Installation (Mac)

Python 3.10 oder neuer wird gebraucht (`python3 --version`; sonst über python.org installieren).

Alle Befehle laufen im entpackten Ordner `flowtrack`, in dem `README.md` und `requirements.txt` liegen. Wechsle **nicht** in den inneren Ordner `flowtrack/flowtrack`, dort liegt nur der Programmcode.

```bash
cd flowtrack          # der Ordner mit README.md
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Beim ersten Kamerazugriff fragt macOS nach der Erlaubnis für das Terminal. Die Erlaubnis lässt sich unter Systemeinstellungen → Datenschutz → Kamera erteilen.

## 2. Ohne Kamera ausprobieren

```bash
python3 -m flowtrack run --source demo --render --dry-run
```

Es öffnen sich zwei Fenster. Das Fenster **camera** zeigt ein simuliertes Bild mit Feuerpunkten, das Fenster **output** die eigenen Effekte. Die Effekte wechselst du mit den Tasten `1`–`4` (Spuren, Wellen, Funken, Kaleidoskop) oder mit `n`. `--dry-run` schickt nichts an Resolume und zeigt die OSC-Nachrichten nur im Terminal an.

Die Variante `--source demo-color` simuliert grüne LED-Poi. Dafür musst du in `config.yaml` `detect: color` setzen.

Die Kommentare in `config.yaml` und die Meldungen im Terminal sind auf Englisch.

## 3. Resolume vorbereiten

1. Unter **Avenue → Einstellungen → OSC** „OSC Input“ einschalten (Port 7000).
2. Unter **Einstellungen → Webserver** „Enable Webserver & REST API“ einschalten (Port 8080, ab Avenue 7.8).
3. Für Layer 1 einen Effekt mit Positionsreglern hinzufügen, zum Beispiel **Transform**. Effekte mit Mittelpunkt eignen sich genauso.
4. Die richtige OSC-Adresse findest du über **Shortcuts → Edit OSC**: Klick auf den Regler, dann steht die Adresse unten. Trag sie in `config.yaml` unter `outputs` ein.

Ohne OSC-Adressen geht es auch. Dieser Befehl listet alle Regler deiner Komposition auf:

```bash
python3 -m flowtrack discover --filter transform
```

Den Pfad (oder einen eindeutigen Teil davon) trägst du dann als `param:` ein. flowtrack setzt den Wert über die WebSocket-API und rechnet ihn automatisch auf den Bereich des Reglers um.

## 4. Mit Kamera

```bash
python3 -m flowtrack run                 # Kamera 0, Einstellungen aus config.yaml
python3 -m flowtrack run --source 1      # andere Kamera (z. B. iPhone per Continuity-Kamera)
python3 -m flowtrack run --render        # zusätzlich eigene Effekte
```

Tasten im Kamerafenster:

| Taste | Funktion |
|---|---|
| `+` / `-` | Helligkeitsschwelle anpassen |
| `m` | Maske einblenden (rot = das, was erkannt wird) |
| `q` | Beenden |

**Ohne IR-Kamera:** Dreh die Belichtung der Kamera herunter. Bei Webcams geht das über `exposure` in `config.yaml`. Beim iPhone über Continuity-Kamera lässt sich die Belichtung kaum einstellen, dort hilft vor allem eine höhere Schwelle. Danach erhöhst du die Schwelle, bis nur noch die Flammen rot markiert sind. Bei LED-Poi stellst du `detect: color` ein und verwendest eine Farbe, die in deinen Visuals nicht vorkommt.

**KI-Körpererkennung (ohne IR, mit jeder Kamera):** Setz in `config.yaml` `detect: pose`. MediaPipe findet dann Hände, Handgelenke, Füße oder die Körpermitte, auch wenn Licht auf den Artisten projiziert wird. Welche Punkte zählen, legst du mit `pose_points` fest. Beim ersten Start lädt flowtrack das Modell herunter (ca. 6 MB). Damit folgen die Effekte dem Körper und den Händen statt der Prop-Spitze, was bei schnellen Poi oft sogar ruhiger aussieht. Der Modus `mode: centroid` nimmt die Mitte aller Punkte, und `spread` entspricht dann dem Abstand der Hände.

**Schnelle Bewegungen:** `lead_ms` schiebt die Position etwas in die Zukunft und gleicht so einen Teil der Verzögerung aus. Im Test mit 100 ms Verzögerung sank der mittlere Versatz damit von etwa 6,7 % auf 2,6 % der Bildbreite. Fängt der Punkt an zu zappeln, verkleinerst du `lead_ms` oder `beta`.

**Mit IR-Kamera:** Bild und Schwelle wie oben einstellen. Die Projektion ist für die Kamera dann unsichtbar.

## 5. Kalibrieren (Kamera ↔ Beamer)

Erst durch die Kalibrierung trifft der Effekt genau den Artisten. Dafür müssen Kamera und Beamer fest stehen.

```bash
python3 -m flowtrack calibrate
```

Der Beamer zeigt vier Markierungen. Für jede Markierung (die große) gibt es zwei Wege:
- im Kamerabild auf die Markierung klicken, **oder**
- **Leertaste** drücken, dann nimmt flowtrack den hellsten Punkt. Hat die Kamera einen IR-Filter, sieht sie den Beamer nicht. Dann hältst du eine Taschenlampe oder ein Feuerzeug an die projizierte Markierung.

Zum Schluss mit **Enter** speichern. Das Ergebnis landet in `calibration.json`. Die Position des Beamer-Bildschirms trägst du in `config.yaml` unter `projector_window` ein.

Ohne Kalibrierung funktioniert alles trotzdem, die Positionen beziehen sich dann einfach auf das Kamerabild.

## 6. Regeln (automatische Steuerung)

In `config.yaml` unter `rules`, zum Beispiel:

```yaml
rules:
  - name: Feuer an
    when: present          # Feuer im Bild …
    for: 0.3               # … seit 0,3 s
    do: {clip: [2, 1]}     # → Layer 2, Clip 1 starten
  - name: Schnell
    when: "speed > 1.0"
    cooldown: 4
    do: {effect: next}     # eigenen Effekt wechseln
```

Für Bedingungen stehen `present`, `absent` oder `merkmal > zahl` zur Verfügung. Mögliche Merkmale sind `x`, `y`, `speed`, `count` (Anzahl Props) und `spread` (Abstand der Props). Als Aktionen gibt es `clip: [layer, clip]`, `osc: adresse` (mit `value`), `param: pfad` (mit `value`) und `effect: name|next`.

## 7. Eigene Effekte in Resolume (Syphon)

Mit `--render` und dem installierten `syphon-python` erscheint in Resolume unter **Sources → Syphon** die Quelle „flowtrack“. Du mischst sie dann wie einen normalen Clip, etwa mit Blend-Mode „Add“ über deine Visuals.

## Dateien

| Datei | Inhalt |
|---|---|
| `flowtrack/source.py` | Kamera, Videodatei, Demo |
| `flowtrack/tracker.py` | Erkennung (Helligkeit/Farbe), One-Euro-Glättung, Vorhersage, Kalibrierung |
| `flowtrack/pose.py` | KI-Körpererkennung (MediaPipe) |
| `flowtrack/resolume.py` | OSC, REST-Auslesen, WebSocket-Setzen |
| `flowtrack/control.py` | Mappings und Regeln |
| `flowtrack/render.py` | eigene Effekte, Syphon |
| `flowtrack/calibrate.py` | Kalibrierung |

## Bekannte Grenzen (Prototyp)

- Bälle und Keulen ohne Licht oder Farbe werden noch nicht direkt erkannt. Der Pose-Modus folgt stattdessen den Händen. Die direkte Erkennung der Props bräuchte ein eigens trainiertes Modell (z. B. YOLO).
- Die OSC-Adressen in `config.yaml` sind Beispiele. Prüf sie in Resolume mit „Edit OSC“.
- Die Syphon-Ausgabe und die Kamera-Belichtung ließen sich ohne Mac nicht testen. Getestet sind Erkennung, Effekte, Regeln, OSC, REST und WebSocket, und zwar gegen einen nachgebauten Resolume-Server.
