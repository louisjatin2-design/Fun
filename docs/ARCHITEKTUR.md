# Architektur (v2, UEF)

```
Spiel (Steam, unverändert)              Spieldateien (nur lesen)
   ▲ SendInput (Maus/Tastatur)             gamedata/textures.scd  → Icons des Baumenüs, Strategie-Symbole
   │                  │ Bildstrom (mss/dxcam)   gamedata/units.scd     → Blueprints (Kategorien, Sortierung)
   │                  ▼                         gamedata/lua.scd       → Standard-Tastenbelegung
supcombot/game.py      Fenster, Frames, Klicks, Baumenü lesen      %LOCALAPPDATA%/.../Game.prefs → eigene Tasten
supcombot/ui.py        UI-Erkennung ohne Kalibrierung (Icons, Leisten, Idle-Buttons, Tabs)
supcombot/gamefiles.py Zugriff auf die scd-Archive, DDS-Dekodierung, Keymap
supcombot/camera.py    Welt ↔ Bildschirm bei voller Herauszoom-Stufe (Kartenrechteck)
supcombot/livevision.py Bildstrom + Wahrnehmungs-Thread (Wirtschaft, Idle-Buttons, Armee, Gegner)
supcombot/bot.py       Hauptschleife (Worker-Thread, ~2,5 s Takt)
   ├── planner/builder.py     Wunschliste, Bauplätze, Eröffnung
   ├── planner/production.py  Fabrik-Warteschlangen (Ingenieure zuerst, dann Armee-Mix, T2/T3)
   ├── planner/economy.py     Stall-/Float-Logik aus Leisten + Einkommensvorzeichen, Budgets
   ├── planner/attack.py      Schwelle, Zielwahl, Wellen, Rückzug
   ├── layouts.py             Layout-Gedächtnis je Karte/Start
   └── ollama.py              optionaler KI-Berater
supcombot/overlay.py   tkinter-Overlay, globale Hotkeys
supcombot/maps.py      Karten aus dem Steam-Ordner (Marker, Vorschaubild)
supcombot/uef.py       Blueprint-IDs, Tiers, Footprints der UEF
```

## Warum keine Kalibrierung mehr nötig ist

| Was der Bot wissen muss | Woher er es nimmt |
|---|---|
| Wo im Baumenü welches Gebäude/welche Einheit liegt | Die Icon-Texturen des Spiels (`<id>_icon.dds`) werden auf die Baumenü-Zeile gelegt (normierte Kreuzkorrelation). Treffer ≥ 0,6 ⇒ Slot gefunden. Die Slot-Größe (48 px bei 100 % Windows-Skalierung) wird daraus gemessen. |
| Reiter T1/T2/T3 | fester Abstand links oben vom ersten Slot (aus dem Screenshot vermessen, skaliert mit der Slot-Größe) |
| Masse-/Energie-Füllstand | grüne bzw. orange Leiste oben links per Farbe; die längste je gesehene Füllung ist 100 % (am Spielstart sind die Speicher voll) |
| Einkommen positiv/negativ | Farbe der großen Zahl rechts neben der Leiste (grün/rot) |
| Idle-Ingenieur / Idle-Fabrik | Unit-Icon (uel0105 …) in der Avatar-Spalte rechts |
| Startposition | ACU auswählen (Spiel-Taste oder Bildmitte), ganz herauszoomen: der Startmarker mit den weißen Auswahlklammern ist unserer |
| Teamfarbe / Gegnerfarben | Farbe des ACU-Symbols am eigenen bzw. an den anderen Startmarkern |
| Kartenrechteck | nicht-schwarzer Bereich bei voller Herauszoom-Stufe, UI-Ränder ausgeblendet |
| Welche Karte | Korrelation mit dem Vorschaubild der `.scmap` |
| Tasten (Angriff, Patrouille, ACU) | `defaultKeyMap.lua` des Spiels, überschrieben durch `Game.prefs` |

## Tick-Ablauf

1. Wirtschaftsanzeige sichtbar? Sonst „Warte auf Spielstart“. 40 s unsichtbar nach der Eröffnung ⇒ Spielende.
2. Einmalig: Startposition und Farben erkennen (siehe oben).
3. Ganz herauszoomen (Mausrad), Kartenrechteck alle 5 Ticks neu prüfen.
4. Eröffnung (einmalig): ACU auswählen → Baumenü lesen → Fabrik, Mex, Generator … per Shift-Klick queuen.
5. Idle-Ingenieur-Button sichtbar? → klicken → Baumenü lesen (T1/T2/T3 am Inhalt erkennen) → bis zu 3 Aufträge
   aus der Wunschliste (Icon klicken, Bauvorschau prüfen, Shift-Klick auf die Weltposition). Sonst Fabrik assistieren.
6. Idle-Fabrik-Button oder Fabrik seit 100 s nicht bedient? → auswählen → Land/Luft am Menü erkennen → Einheiten queuen,
   Sammelpunkt setzen. Upgrade-Icon (T2/T3-Fabrik) im Menü ⇒ Upgrade, wenn die Wirtschaft es erlaubt.
7. ACU alle 75 s: Generatoren/zweite Fabrik/Verteidigung oder Fabrik assistieren.
8. Mex-Upgrade: Mex anklicken → Upgrade-Icon im Menü → klicken.
9. Gegner in der Basis ⇒ Gegenangriff vom Sammelpunkt; viele Gegner ⇒ ACU zurück.
10. Angriffswellen ab Schwelle: Box-Auswahl am Sammelpunkt, Attack-Move (Spiel-Taste „attack“ + Klick).

## Sicherheit

- Jede Eingabesequenz prüft ein Abbruch-Flag; Ctrl+Alt+B setzt es und lässt gehaltene Tasten los.
- Keine Eingaben, wenn das Spielfenster nicht im Vordergrund ist oder du die Maus bewegst (4 s Pause).
- `run --dry-run` loggt alle Eingaben, sendet aber nichts.
