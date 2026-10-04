# SupComBot – externer UEF-Bot für Supreme Commander: Forged Alliance (Steam)

Eigenständige Windows-App, die das **unveränderte Steam-Spiel** spielt: keine Mod, kein FAF, kein Eingriff ins Spiel.
Der Bot sieht das Spiel per Bildschirmaufnahme, liest Karten und Icons aus deinem Steam-Ordner und spielt mit
Maus- und Tastatureingaben. Ein kleines Overlay zeigt, was er gerade tut.

**Version 2: Plug and Play.** Keine Kalibrierung mehr. Installieren, Spiel als UEF starten, `start.bat`, Ctrl+Alt+B.

## 1. Installation (Copy & Paste)

Voraussetzungen: Windows 10/11, Steam-Version von Forged Alliance, **Python 3.10+**
(python.org, Haken bei „Add python.exe to PATH“), **Git** (git-scm.com).

Eingabeaufforderung öffnen (Win+R → `cmd` → Enter) und einfügen:

```bat
cd /d "%USERPROFILE%\Documents"
git clone -b main https://github.com/louisjatin2-design/Fun.git SupComBot
cd SupComBot
install.bat
```

Wichtig ist `-b main`: Der Standard-Branch des Repos enthält noch das alte Spiel.

Python und Git fehlen noch? In PowerShell einfügen, danach das Fenster schließen und ein neues öffnen:

```powershell
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
```

Schon vorhanden? Dann im SupComBot-Ordner:

```bat
.\update.bat
```

## 2. Spielen

1. Steam → Forged Alliance → Eigenschaften → Startoptionen: `/windowed` (Fenstermodus ist Pflicht, sonst sind
   Overlay und Bildschirmaufnahme nicht möglich). Das Fenster darf beliebig groß sein, auch maximiert.
2. Skirmish oder Multiplayer als **UEF** starten.
3. Im SupComBot-Ordner:

```bat
.\start.bat
```

4. Sobald das Spiel läuft: **Ctrl+Alt+B** schaltet den Bot ein. Er übernimmt dann Maus und Tastatur in kurzen Schüben.
   Bewegst du die Maus selbst, pausiert er 4 Sekunden. Ctrl+Alt+B schaltet ihn sofort wieder aus.

Der Bot erkennt selbst: deine Auflösung, das Baumenü, die Wirtschaftsleisten, die Karte, deine Startposition,
deine Teamfarbe und die Gegnerfarben, die Tastenbelegung des Spiels. Es gibt nichts einzustellen.

| Hotkey | Funktion |
|---|---|
| Ctrl+Alt+B | Bot ein/aus (sofortiger Stopp aller Eingaben) |
| Ctrl+Alt+A | Automatische Angriffe ein/aus |
| Ctrl+Alt+X | Jetzt mit allem am Sammelpunkt angreifen |
| Alt+F6 | Overlay ein-/ausblenden |
| Ctrl+Alt+W / Ctrl+Alt+L | Sieg / Niederlage melden (Layout-Gedächtnis, Spielbericht) |
| Ctrl+Alt+N | Neues Spiel (Zustand zurücksetzen) |
| Ctrl+Alt+Q | Beenden |

Overlay: Bot, Auto-Angriff, Strategie (auto / balanced / eco / rush / turtle), Start-Slot (falls die Erkennung
daneben liegt), Slots als Verbündete markieren (Teamspiele), „Bot-Sicht“ zeigt live, was der Bot erkennt.

## 3. Was der Bot spielt (UEF)

- **Eröffnung**: Landfabrik, 2 Mex, Generator, 2 Mex, 2 Generatoren per ACU, danach assistiert der ACU oder baut
  Generatoren, zweite Fabrik und Verteidigung.
- **Ingenieure**: Fabriken bauen erst Ingenieure (bis zum Ziel, Standard 14), Ingenieure bauen Hydro, Mex im
  wachsenden Radius, Generatoren nach Bedarf, Radar, weitere Land- und Luftfabriken, Punktverteidigung, Flak,
  Massenspeicher neben Mex; ohne Aufgabe assistieren sie die Fabrik.
- **Produktion**: Striker/Lobo/Archer/Snoop-Mix nach Strategie, Luftfabrik baut Späher und Abfangjäger.
  Sammelpunkt Richtung Gegner.
- **Wirtschaft**: Masse-/Energie-Speicher und das Vorzeichen des Einkommens werden gelesen. Stall ⇒ weniger
  Aufträge, mehr Mex/Generatoren. Überschuss ⇒ mehr Fabriken, Mex-Upgrades (T2, später T3).
- **Tech 2/3**: Fabrik-Upgrade ab etwa 7–8 Minuten bei guter Wirtschaft, T2-Ingenieure, Pillar, Sky Boxer, T2-Generatoren,
  Schild, T2-Flak/PD, T2-Radar; T3 ab etwa 18 Minuten (Titan, T3-Ingenieure, T3-Generator, SAM).
- **Kampf**: Wellen ab Schwelle (Standard 16 Einheiten) auf gegnerische Expansionen, dann Basis; Wellen werden
  verfolgt, ziehen sich bei Übermacht zurück und ziehen weiter. Gegner in der Basis lösen einen Gegenangriff aus,
  bei vielen Gegnern zieht sich der ACU zurück.
- **Gedächtnis**: nach einem Sieg wird das Basislayout je Karte/Start gespeichert und wiederverwendet; Strategie
  „auto“ nimmt die Strategie mit der besten Siegquote.

## 4. Wenn etwas nicht klappt

```bat
.\doctor.bat
```

Dabei den ACU im Spiel auswählen und ganz herauszoomen. `doctor` prüft Module, Spieldateien, Fenster,
Wirtschaftsleisten, Baumenü-Erkennung, Idle-Button, Kartenrechteck und Karte und legt ein Kontrollbild unter
`%APPDATA%\SupComBot\debug\doctor.png` ab (grün = erkannte Icons, magenta = Reiter, rot = Kartenrechteck).
Schick mir dieses Bild und `%APPDATA%\SupComBot\logs\supcombot.log`, wenn der Bot nichts tut.

| Symptom | Ursache / Lösung |
|---|---|
| „Warte auf Spielstart“ | Wirtschaftsleisten nicht gefunden: Spiel im Vordergrund? Fenstermodus? Läuft ein Spiel (nicht Lobby)? |
| „ACU-Baumenü nicht gefunden“ | Baumenü-Icons aus `textures.scd` nicht lesbar (doctor zeigt es) oder ein anderes UI-Skin |
| „Kartenrechteck nicht erkannt“ | Ganz herauszoomen (Mausrad), die ganze Karte muss sichtbar sein |
| Startposition falsch | Im Overlay „Start-Slot“ klicken |
| Hotkeys reagieren nicht | Konsole „Als Administrator ausführen“ (Modul `keyboard`) |
| Bot klickt daneben | Fenster während des Spiels nicht verschieben/verkleinern; Windows-Skalierung wird erkannt |

Weitere Befehle:

```bat
.\.venv\Scripts\python.exe -m supcombot maps              # erkannte Karten
.\.venv\Scripts\python.exe -m supcombot screenshot        # Screenshot des Spielfensters
.\.venv\Scripts\python.exe -m supcombot test-input        # bewegt die Maus im Quadrat
.\.venv\Scripts\python.exe -m supcombot run --dry-run     # nur planen und loggen
.\.venv\Scripts\python.exe -m supcombot run --map "Seton" # Karte vorgeben
.\.venv\Scripts\python.exe -m supcombot reports --last    # letzter Spielbericht
```

## 5. Einstellungen (optional)

`%APPDATA%\SupComBot\settings.json` wird beim ersten Start angelegt. Alles darin ist optional:

| Schlüssel | Bedeutung |
|---|---|
| `strategy` | `auto`, `balanced`, `eco`, `rush`, `turtle` |
| `auto_attack`, `attack_threshold` | automatische Wellen, Armeegröße am Sammelpunkt |
| `max_engineers` | Ingenieur-Ziel |
| `start_slot` | 0 = automatisch erkennen, sonst Lobby-Slot |
| `ally_slots` | Slots der Verbündeten (auch im Overlay klickbar) |
| `hotkeys` | globale Hotkeys |
| `ollama.enabled` | `auto` (nutzen, wenn Ollama läuft), `true`, `false` |
| `advanced.yield_to_user_seconds` | Pause bei eigener Mausbewegung |

## 6. Ollama (optional)

Läuft Ollama lokal (`ollama serve`, z. B. `ollama pull qwen2.5:14b`), bekommt es alle 30 s den Zustand und darf
Strategie, Aggression, Angriffsschwelle, Ingenieurzahl und Armee-Mix in engen Grenzen anpassen; nach dem Spiel
schreibt es eine kurze Nachbesprechung. Ohne Ollama spielt der Bot ganz normal.

## 7. Grenzen (ehrlich)

- **Ich konnte das Spiel hier nicht starten.** Die Erkennung ist mit Tests und mit deinem Screenshot (2560×1440,
  UEF-Baumenü, Wirtschaftsleisten, Reiter) abgesichert; die Eingaben (Zoom, Platzieren, Attack-Move) musst du beim
  ersten Lauf beobachten. `doctor.bat` und `--debug` zeigen, was der Bot sieht.
- Der Bot teilt sich Maus und Tastatur mit dir. Gleichzeitig selbst spielen geht nicht.
- Er sieht Einheiten nur als Farbpunkte in Teamfarbe bei voller Herauszoom-Stufe; Verluste werden geschätzt.
- Marine, Experimentals, ACU-Upgrades und Transporte fehlen. Nur UEF.
- Ob Eingabe-Automation in einer Multiplayer-Runde erwünscht ist, entscheidet die Runde, mit der du spielst.

## 8. Wie es funktioniert

Siehe [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md). Kurz: Der Bot liest die Baumenü-Icons aus `gamedata\textures.scd`
deiner Installation und findet sie per Bildvergleich auf dem Bildschirm, liest Leisten per Farbe, arbeitet auf
voller Herauszoom-Stufe und bildet Weltkoordinaten linear auf das erkannte Kartenrechteck ab.

## 9. Entwicklung

```bat
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

Die Planungsmodule und die UI-Erkennung sind reine Logik und laufen auf jedem System (Tests mit synthetischen Bildern).
