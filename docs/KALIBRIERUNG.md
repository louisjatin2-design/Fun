# Kalibrierung

Profil = Fraktion + Client-Auflösung, gespeichert unter `%APPDATA%\SupComBot\profiles\<fraktion>_<B>x<H>.json`.

## Vorbereitung im Spiel

- Fenstermodus (`/windowed`), feste Auflösung, Skirmish gegen eine KI (am besten „Easy“, damit Zeit bleibt).
- Baue einen Ingenieur und eine Fabrik, damit die Idle-Symbole in der Avatar-Leiste rechts erscheinen.
- Lass das Spiel im Vordergrund, wenn du F8 drückst (die Konsole liest die Mausposition global).

## Schritte des Assistenten

| Schlüssel | Was zeigen | Pflicht |
|---|---|---|
| ui.exclude.top / right / bottom | Kanten der UI-Leisten (werden bei der Kartenerkennung ausgeblendet) | ja |
| ui.idle_engineer | Idle-Ingenieur-Symbol (rechte Leiste) | ja |
| ui.idle_factory | Idle-Fabrik-Symbol | optional |
| ui.build.landFac / airFac / pgen / mex | Buttons im T1-Baumenü (ACU oder Ingenieur ausgewählt) | ja |
| ui.build.hydro / massStorage / pd / aa / radar | weitere T1-Buttons | optional |
| ui.build.tab_t2, pgen2, pd2, aa2, shield2 | T2-Reiter und -Buttons (nur mit T2-Ingenieur) | optional |
| ui.factory.land.eng / tank | Fabrik-Buttons (Landfabrik ausgewählt) | ja |
| ui.factory.land.arty / maa / scout | weitere Land-Einheiten | optional |
| ui.factory.air.scout / inter / bomber | Luftfabrik | optional |
| ui.upgrade | Upgrade-Button bei ausgewähltem Mex | optional |
| ui.factory.upgrade | Upgrade-Button (T2-HQ) bei ausgewählter Landfabrik | optional |
| ui.factory.repeat | Wiederholen-/Endlos-Button im Fabrikmenü | optional |
| ui.factory.tab_t2, land.eng2, land.tank2, land.maa2 | T2-Reiter und T2-Einheiten (nach dem Upgrade) | optional |
| colors.enemy | Symbol einer Gegner-Einheit (pro Gegnerfarbe wiederholen) | optional |
| ui.eco.mass_left / mass_right / energy_left / energy_right | Enden der Speicherleisten oben | ja |
| colors.team | dein ACU-Symbol bei voller Herauszoom-Stufe (Teamfarbe) | ja |
| Karte | ganz herausgezoomt: Kartenrechteck wird erkannt, sonst zwei Ecken zeigen | ja |

Für jeden Button wird ein 24×24-Referenzbild gespeichert. Damit erkennt der Bot später, ob das Baumenü
oder das Idle-Symbol wirklich sichtbar ist (Patch-Ähnlichkeit ≥ 0,78).

## Kontrolle

- `%APPDATA%\SupComBot\debug\maprect_<karte>.png` zeigt das erkannte Kartenrechteck (rot).
- `python -m supcombot detect-map` prüft die Kartenerkennung.
- `python -m supcombot run --dry-run --debug` zeigt im Log, wohin geklickt würde.

## Typische Probleme

| Symptom | Ursache / Lösung |
|---|---|
| „Kartenrechteck nicht erkannt“ | UI-Ausschlusskanten falsch, Spiel nicht ganz herausgezoomt, Karte füllt den Bildschirm (dann Ecken manuell zeigen) |
| Bot klickt daneben | Auflösung geändert → neu kalibrieren; Fenster verschoben ist egal (Client-Koordinaten) |
| „ACU nicht auswählbar“ | Start-Slot falsch (Overlay „Start-Slot +“) oder ACU schon weggelaufen |
| Keine Ingenieur-Aufträge | Idle-Symbol-Referenz passt nicht mehr (`--only ui.idle_engineer`) |
| Mex wird nicht gebaut | Kartenrechteck ungenau → `--map-rect`; bei großen Karten `precision_zoom_notches` setzen |
| Hotkeys reagieren nicht | `keyboard`-Modul braucht evtl. Admin-Rechte; Konsole „Als Administrator ausführen“ |
