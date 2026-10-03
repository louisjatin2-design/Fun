# Architektur

```
Spiel (Steam, unverändert)
   ▲ SendInput (Maus/Tastatur)          │ Screenshots (mss)
   │                                    ▼
supcombot/game.py  ── click_ui / ui_visible ──┐   Profil (Kalibrierung, %APPDATA%\SupComBot\profiles)
supcombot/camera.py ── Welt ↔ Bildschirm ─────┤   Kartenrechteck bei voller Herauszoom-Stufe
                                              ▼
supcombot/bot.py  (Worker-Thread, ~3 s Takt)
   ├── planner/economy.py     Leisten lesen, Stall, Budgets
   ├── planner/builder.py     Wunschliste, Bauplätze (Spirale, Layout-Slots), Eröffnung
   ├── planner/production.py  Fabrik-Queues (Ingenieure zuerst, dann Armee-Mix)
   ├── planner/attack.py      Schwelle, Zielwahl, Wellen
   ├── layouts.py             Layout-Gedächtnis je Karte/Start (JSON)
   └── ollama.py              Zustand → JSON-Rat (Hintergrund-Thread)
supcombot/overlay.py  (tkinter, Hauptthread, Hotkeys via `keyboard`)
supcombot/maps.py     (Steam-Ordner, *_scenario.lua, *_save.lua, .scmap-Vorschau)
```

## Tick-Ablauf

1. Spiel im Vordergrund? Sonst warten.
2. Kamera ganz herauszoomen (Mausrad, 40 Stufen), Kartenrechteck erkennen (jeder 5. Tick) oder gespeichertes nutzen.
3. Screenshot → Masse-/Energie-Füllstand (Leisten), Teamfarben-Blobs am Sammelpunkt (Armee-Schätzung),
   Sieg-/Niederlage-Vorlage.
4. Eröffnung (einmalig): ACU am Startmarker anklicken, Landfabrik + Mex + Generatoren + Mex per Shift-Klick queuen.
5. Idle-Ingenieur-Symbol sichtbar? → anklicken → Baumenü sichtbar? → bis zu 3 Aufträge aus der Wunschliste
   (Button klicken, Shift-Klick auf Weltposition) → Esc, Abwahl. Max. 2 Ingenieure pro Tick.
6. Idle-Fabrik-Symbol sichtbar (oder bekannte Fabrik seit 90 s nicht bedient)? → auswählen → Panel-Art erkennen
   (Land/Luft) → 1–4 Einheiten queuen → Sammelpunkt per Rechtsklick setzen.
7. Wirtschaft erlaubt Upgrade? → nächsten T1-Mex anklicken → Upgrade-Button.
8. Auto-Angriff an und Schwelle erreicht? → Box-Auswahl am Sammelpunkt → Alt+Rechtsklick auf Ziel.
9. Alle 15 s Zustand als JSON ins Log, alle 45 s an Ollama (Rat gilt 3 Minuten).

## Wahrnehmung ohne Spielzugriff

| Information | Quelle |
|---|---|
| Mex-/Hydro-Punkte, Startpositionen, Kartengröße | `*_save.lua`, `*_scenario.lua` im Steam-Ordner |
| Welche Karte läuft | Korrelation Screenshot ↔ `.scmap`-Vorschau |
| Welt → Bildschirm | lineare Abbildung auf das Kartenrechteck (volle Herauszoom-Stufe) |
| Masse/Energie | Füllstand der Speicherleisten (Helligkeit entlang einer kalibrierten Linie) |
| Idle-Ingenieure/-Fabriken | Referenzbild des Avatar-Symbols (Patch-Vergleich) |
| Auswahl erfolgreich | Referenzbild eines Baumenü-Buttons sichtbar |
| Armeegröße | Blobs in Teamfarbe im Sammelpunkt-Rechteck |
| Spielende | Vorlage des Sieg-/Niederlage-Dialogs oder Hotkey |
| Alles andere | eigene Buchführung (`state.py`) |

## Determinismus und Sicherheit

- Jede Eingabesequenz prüft ein Abbruch-Flag; Ctrl+Alt+B setzt es und lässt gehaltene Tasten los.
- Keine Eingaben, wenn das Spielfenster nicht im Vordergrund ist.
- `--dry-run` loggt alle Eingaben, sendet aber nichts.
