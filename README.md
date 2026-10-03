# SupComBot – externer Bot für Supreme Commander: Forged Alliance (Steam)

Eigenständige Windows-App, die das **unveränderte Steam-Spiel** steuert: keine Mod, kein FAF-Loader.
Der Bot sieht das Spiel per Screenshot, liest Kartendaten direkt aus dem Steam-Ordner und spielt
mit **Maus- und Tastatureingaben** (SendInput). Ein Overlay-Fenster über dem Spiel zeigt Status und Schalter.

**Funktionen**

- Kartenanalyse: Mass-/Hydro-Punkte und Startpositionen aus `<map>_save.lua`, Kartenerkennung per Vorschaubild (`.scmap`)
- Bauen: ACU-Eröffnung, Ingenieure bekommen Mex, Generatoren, Fabriken, Radar, Verteidigung, Speicher (Prioritätenliste)
- Produktion: Fabriken werden mit Ingenieuren und einer Armee-Mischung befüllt, Sammelpunkt wird gesetzt
- Wirtschaft: Masse-/Energie-Speicherleisten werden gelesen, Stall-Schutz, Mex-Upgrades nach Budget
- Angriffe: per Hotkey ein/aus, Wellen ab einstellbarer Schwelle, Ziele = gegnerische Expansionen, dann Basis
- Ollama: lokale KI bewertet den Zustand alle 45 s und passt Strategie, Schwelle, Ingenieur-Zahl, Armee-Mix an
- Layout-Gedächtnis: nach einem Sieg wird das Basis-Layout je Karte + Startposition gespeichert und beim
  nächsten Spiel bevorzugt wiederverwendet (zwei Niederlagen in Folge verwerfen es), per Schalter abschaltbar
- **Live-Sicht**: kontinuierlicher Bildstrom des Spielfensters (dxcam/Desktop Duplication, Fallback mss) statt
  Einzel-Screenshots; eine Wahrnehmungsschicht wertet mehrmals pro Sekunde aus (Wirtschaft, Idle-Symbole, Armee am
  Sammelpunkt, Gegner nahe Basis, Spielende) und ein Vorschaufenster „Bot-Sicht“ zeigt, was der Bot sieht
- Automatische Verteidigung: Gegner-Symbole in der Basis lösen einen Gegenangriff vom Sammelpunkt aus
- Overlay mit allen Schaltern, Strategie (balanced/eco/rush/turtle), Aggression, Schwellen, globale Hotkeys

> **Wichtig:** Der Bot kann nicht getestet werden, ohne dass das Spiel läuft. Alle Spiel-Positionen
> (Buttons, Leisten) werden einmalig mit dem Kalibrier-Assistenten auf deinem PC aufgenommen. Lies
> den Abschnitt „Bekannte Grenzen“ bevor du dich wunderst.

---

## 1. Installation (Copy & Paste)

Voraussetzungen: Windows 10/11, Steam-Version von Forged Alliance, **Python 3.10+** (python.org, Haken bei
„Add python.exe to PATH“), **Git** (git-scm.com). Ollama ist optional.

Eingabeaufforderung öffnen (Win+R → `cmd` → Enter) und Zeile für Zeile einfügen:

```bat
cd /d "%USERPROFILE%\Documents"
git clone -b main https://github.com/louisjatin2-design/Fun.git SupComBot
cd SupComBot
.\install.bat
```

Wichtig ist `-b main`: Der Standard-Branch des Repos enthält noch das alte Spiel.

**Schon geklont und `install.ps1` fehlt?** Dann im vorhandenen Ordner auf `main` wechseln:

```bat
cd /d "%USERPROFILE%\SupComBot"
git fetch origin
git checkout main
.\install.bat
```

**Update später** (im SupComBot-Ordner):

```bat
.\update.bat
```

Alle `.bat`-Dateien laufen per Doppelklick, in cmd und in PowerShell (dort mit `.\` davor).

## 2. Spiel vorbereiten

1. Steam → Forged Alliance → Eigenschaften → Startoptionen: `/windowed` (Fenstermodus ist Pflicht,
   sonst ist das Overlay unsichtbar und Screenshots schlagen fehl). Alternativ Borderless-Tool.
2. Im Spiel eine feste Auflösung wählen (z. B. 1920×1080). Das Profil ist an Fraktion + Auflösung gebunden.
3. Skirmish gegen KI starten. Merke dir deinen **Start-Slot** (Lobby-Platz 1..N) und deine Fraktion.

## 3. Einmalig kalibrieren

Im laufenden Skirmish (Spiel im Vordergrund):

```bat
.\calibrate.bat --faction uef
```

Der Assistent sagt dir Schritt für Schritt, worauf du mit der Maus zeigen sollst (Baumenü-Buttons,
Fabrik-Buttons, Idle-Ingenieur-Symbol, Masse-/Energie-Leiste, deine Teamfarbe, Kartenrechteck bei voller
Herauszoom-Stufe). **F8** übernimmt, **F7** überspringt optionale Schritte, **F6** bricht ab.
Pro Fraktion einmal wiederholen (`--faction cybran` usw.). Einzelne Punkte nachbessern:

```bat
.\calibrate.bat --only ui.build.mex ui.idle_engineer
.\calibrate.bat --map-rect
.\calibrate.bat --template victory
.\calibrate.bat --template defeat
```

`--map-rect` nimmt nur das Kartenrechteck auf (pro Karte einmal). `--template` speichert nach einem Sieg bzw. einer
Niederlage den Dialog, damit das Spielende automatisch erkannt wird.

Details: [docs/KALIBRIERUNG.md](docs/KALIBRIERUNG.md).

## 4. Spielen

```bat
.\start.bat
.\start.bat --map "Seton"
.\start.bat --debug
```

Ohne Argument wird die Karte automatisch erkannt. `--map` gibt sie vor, `--debug` schreibt ein ausführliches Log und
Screenshots nach `%APPDATA%\SupComBot\debug`.

Ablauf: Spiel laden → im Spiel ganz herauszoomen → `start.bat` → Overlay erscheint → Start-Slot im
Overlay prüfen („Start-Slot +“) → **Ctrl+Alt+B** schaltet den Bot ein. Der Bot übernimmt dann Maus und
Tastatur in kurzen Schüben (ca. alle 3 s). Solange er an ist, solltest du nicht selbst klicken.

| Hotkey | Funktion |
|---|---|
| Ctrl+Alt+B | Bot ein/aus (sofortiger Stopp aller Eingaben) |
| Ctrl+Alt+A | Automatische Angriffe ein/aus |
| Ctrl+Alt+X | Jetzt mit allem am Sammelpunkt angreifen |
| Ctrl+Alt+S | Strategie wechseln (balanced → eco → rush → turtle) |
| **Alt+F6** | Overlay ein-/ausblenden (Game-Overlay-Stil, auch im Multiplayer) |
| Ctrl+Alt+W / Ctrl+Alt+L | Sieg / Niederlage melden (Layout-Gedächtnis), falls keine Dialog-Vorlage aufgenommen wurde |
| Ctrl+Alt+N | Neues Spiel (Zustand zurücksetzen) |
| Ctrl+Alt+Q | Beenden |

Alle Hotkeys stehen in `%APPDATA%\SupComBot\settings.json` und sind änderbar.

## 5. Ollama

Ollama muss laufen (`ollama serve`) und ein Modell installiert sein, z. B.:

```bat
ollama pull llama3.1
.\.venv\Scripts\python.exe -m supcombot ollama-test
```

`model: "auto"` in den Einstellungen nimmt das erste installierte Modell (bevorzugt llama3/qwen/mistral/gemma/phi).
Die KI bekommt alle 45 s den Zustand (Wirtschaft, Gebäude, Armee-Schätzung, Ereignisse) und antwortet mit JSON;
nur erlaubte, begrenzte Felder werden übernommen. Rat gilt 3 Minuten, danach greifen wieder die Overlay-Einstellungen.
Ohne Ollama läuft der Bot ganz normal.

## 6. Weitere Befehle

```bat
.\.venv\Scripts\python.exe -m supcombot maps          # erkannte Karten mit Mex-Zahl und Start-Slots
.\.venv\Scripts\python.exe -m supcombot detect-map    # welche Karte sieht der Bot gerade?
.\.venv\Scripts\python.exe -m supcombot screenshot    # Screenshot des Spielfensters speichern
.\.venv\Scripts\python.exe -m supcombot test-input    # bewegt die Maus im Quadrat (SendInput-Test)
.\.venv\Scripts\python.exe -m supcombot layouts       # gespeicherte Layouts; --clear löscht alle
.\.venv\Scripts\python.exe -m supcombot run --dry-run # nur planen und loggen, keine Eingaben
```

Dateien: Einstellungen `%APPDATA%\SupComBot\settings.json`, Profile `...\profiles\`, Layouts `...\layouts\`,
Logs `...\logs\supcombot.log`.

## 7. Live-Sicht

Der Bot nimmt das Spielfenster dauerhaft auf (Standard 20 fps, `vision.fps` in `settings.json`). Unter Windows wird
`dxcam` (Desktop Duplication, sehr geringe Latenz) genutzt, sonst `mss`. Der Wahrnehmungs-Thread wertet die Bilder
mit `vision.perception_hz` (Standard 5/s) aus; die Bot-Schleife greift nur noch auf diese Ergebnisse zu und wartet
nie auf einen Screenshot. Die Overlay-Zeile „Live-Sicht“ zeigt fps, Backend, ob die Kartenansicht gerade gültig ist
(ganz herausgezoomt) und wie viele Gegner-Symbole in der Basis erkannt wurden.

- Button **„Bot-Sicht (Live)“** öffnet ein Fenster mit dem Livebild plus Markierungen: Kartenrechteck (blau = gültig,
  orange = nicht herausgezoomt), Start (grün), Sammelpunkt (gelb), Gegnerstarts (rotes X), eigene Bauaufträge
  (Quadrate), letztes Angriffsziel (roter Kreis), erkannte Gegner (rote Punkte). `vision.preview: true` öffnet es automatisch.
- Für die Gegner-Erkennung einmal `.\calibrate.bat --only colors.enemy` ausführen und auf ein Gegner-Symbol zeigen
  (pro Gegnerfarbe wiederholen). Ohne Gegnerfarbe bleibt die Verteidigung passiv.
- Button **„Verteidigung“** (bzw. `auto_defense`) schaltet den Gegenangriff bei Gegnern in der Basis ein/aus.

## 8. Multiplayer

Der Bot ist eine externe App und spielt in jedem Modus, in dem du selbst spielen kannst, also auch LAN/Online-Partien
der Steam-Version. Er liest keinen Spielspeicher, sondern nur den Bildschirm. Zwei Dinge sind anders als im Skirmish:

1. **Lobby-Slots**: Im Overlay gibt es die Zeile „Lobby-Slots“ mit einem Button pro Startposition. Klicken wechselt
   `Ich → Gegner → Ally → leer`. Trage ein, auf welchem Slot du bist, wer Gegner und wer Verbündeter ist (Verbündete
   werden nie angegriffen und nicht als Ziel gezählt). Solange nichts markiert ist, gelten alle anderen Slots als Gegner.
2. **Gegnerfarben**: Menschliche Gegner expandieren überall. Mit `.\calibrate.bat --only colors.enemy` (pro Gegnerfarbe
   einmal, ganz herausgezoomt auf ein gegnerisches Symbol zeigen) scannt die Live-Sicht die **gesamte Karte** und
   Angriffswellen zielen auf gesehene Gegner-Cluster statt nur auf Startpositionen.

Alt+F6 blendet das Overlay ein und aus. Es ist ein eigenes Always-on-top-Fenster, deshalb muss das Spiel im
Fenster-/Borderless-Modus laufen. Hinweis: Ob Eingabe-Automation in einer bestimmten Lobby erwünscht ist, entscheidet
die Runde, mit der du spielst.

## 9. Hardware ausreizen (RTX 3080, Ryzen 9 5900X, 32 GB)

Die Standardwerte (`performance.profile: "max"`) sind auf diese Hardware ausgelegt:

| Komponente | Nutzung |
|---|---|
| RTX 3080 (10 GB) | Ollama mit allen Layern auf der GPU (`num_gpu: 99`), Kontext 8192. Empfohlen: `ollama pull qwen2.5:14b` (ca. 9 GB VRAM, deutlich bessere Ratschläge als 7B/8B). Fallback `llama3.1:8b`. Rat alle 20 s. |
| 5900X (12 Kerne) | Capture mit 60 fps (dxcam), Wahrnehmung 15×/s über die ganze Karte mit OpenCV-Multithreading (`performance.threads: 0` = alle Kerne bis auf zwei, die dem Spiel bleiben). |
| 32 GB RAM | Bildpuffer und Modell-Kontext sind unkritisch; nichts weiter nötig. |

```bat
ollama pull qwen2.5:14b
.\.venv\Scripts\python.exe -m supcombot ollama-test
```

Der Test zeigt das gewählte Modell und die GPU-Optionen.

Schwächerer PC: `"performance": {"profile": "low"}` in `settings.json` (15 fps, 4 Auswertungen/s, nur Basis-Scan).
Die Reihenfolge der bevorzugten Modelle steht unter `ollama.prefer`.

## 10. Wie es funktioniert

Siehe [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md). Kurz: Der Bot arbeitet auf **voller Herauszoom-Stufe**,
dort ist die ganze Karte sichtbar und Weltkoordinaten lassen sich linear auf das erkannte Kartenrechteck
abbilden. Mass-Punkte werden so auf 1–2 Pixel genau getroffen, der Mex-Bauplatz rastet im Spiel von selbst ein.
Einheiten erkennt der Bot über die Idle-Symbole der Avatar-Leiste (Ingenieure, Fabriken) und über Farbblobs
in Teamfarbe am Sammelpunkt (Armee-Schätzung). Alles andere ist eigene Buchführung.

## 11. Bekannte Grenzen (ehrlich)

- **Ungetestet gegen das echte Spiel.** Ich konnte das Spiel hier nicht starten. Die Logik ist mit Tests und einem
  Dry-Run abgesichert, die Spiel-Interaktion (Buttons, Zoomverhalten, Attack-Move) musst du beim ersten Lauf prüfen.
  `--debug` legt Screenshots ab, das Log zeigt jede Eingabe.
- Der Bot teilt sich Maus und Tastatur mit dir. Gleichzeitiges Spielen geht nicht; Ctrl+Alt+B stoppt sofort.
- Gegner-Wahrnehmung nur über kalibrierte Gegnerfarben in der Basis-Umgebung. Angriffsziele sind bekannte
  Positionen (Mex-Punkte auf Gegnerseite, Startpunkt), keine Rückzugslogik. Verluste werden über Wellen geschätzt.
- Bauplätze werden nicht auf Gültigkeit geprüft. Ungültige Plätze (Klippen, Wasser) ignoriert das Spiel stillschweigend;
  der Bot glaubt dann, gebaut zu haben. Siege merken sich daher nur Layouts, die funktioniert haben.
- Einkommenswerte werden nicht gelesen (nur Speicher-Füllstände). Daher zeitbasierte Budgets.
- Fabrik-Upgrades auf T2/T3 und T2-Gebäude sind nur vorbereitet (optionale Kalibrierpunkte), nicht aktiv geplant.
- Der Attack-Move ist als Alt+Rechtsklick konfiguriert; falls dein Spiel anders belegt ist, in `settings.json`
  unter `input.attack_move_modifier` ändern (`"alt"`, `"ctrl"`, `"shift"` oder leer für normalen Rechtsklick).
- Karten > 20 km (2048 Einheiten) haben bei 1080p nur 0,5 px pro Einheit; dort hilft
  `input.precision_zoom_notches` (z. B. 6): vor jedem Klick wird am Cursor hineingezoomt und wieder heraus.

## 12. Vorschläge Quality of Life (noch nicht gebaut)

1. **OCR der Einkommenszahlen** (pytesseract) für echte Masse-/Energie-Bilanz statt Füllstandsheuristik.
2. **Gegner-Icons auf der ganzen Karte** (nicht nur in der Basis) für Rückzug und dynamische Zielwahl.
3. **Bauplatz-Prüfung** per Farbe der Bauvorschau (grün/rot) vor dem Klick.
4. **Automatische Start-Slot-Erkennung**: ACU-Icon in Teamfarbe am Spielstart suchen und dem nächsten ARMY-Marker zuordnen.
5. **Fabrik-Upgrades und T2/T3-Produktion** mit zusätzlichen Kalibrierpunkten.
6. **Build-Order-Profile pro Karte** als editierbare JSON, inkl. Export/Import der Layouts.
7. **Overlay-Minikarte** mit geplanten Bauplätzen und Angriffsziel (Live-Kontrolle, was der Bot vorhat).
8. **Sprachausgabe/Chat-Log** der Ollama-Ratschläge, plus Button „Rat verwerfen“.
9. **Replay-Auswertung**: nach dem Spiel Log + Ereignisse an Ollama geben und eine Nachbesprechung erzeugen.
10. **Tray-Icon** statt Konsole, Autostart mit dem Spiel.

## 13. Entwicklung

```bat
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

Alle Planungsmodule (`supcombot/planner`) sind reine Logik ohne Bildschirmzugriff und laufen auf jedem System.
