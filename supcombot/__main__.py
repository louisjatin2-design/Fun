"""Command line entry point: python -m supcombot [run|doctor|maps|screenshot|test-input|reports|layouts]."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config, layouts, log as logmod, win
from .gamefiles import GameFiles
from .maps import find_map, list_maps, match_map, steam_game_dir


def _game_dir(settings: dict):
    gd = settings.get("game_dir")
    return Path(gd) if gd else steam_game_dir()


def _advisor(settings: dict):
    from .ollama import OllamaAdvisor

    o = settings.get("ollama", {})
    return OllamaAdvisor(o.get("url", "http://localhost:11434"), o.get("model", "auto"), 60, "de")


def _make_advisor(settings: dict, log):
    o = settings.get("ollama", {})
    mode = str(o.get("enabled", "auto")).lower()
    if mode in ("false", "0", "off", "no", "aus"):
        return None
    adv = _advisor(settings)
    if adv.check():
        return adv
    if mode == "auto":
        log.info("Ollama nicht erreichbar - Bot laeuft ohne KI-Berater (das ist in Ordnung).")
    else:
        log.warning("Ollama aktiviert, aber nicht erreichbar: %s", adv.last_error)
    return None


# ------------------------------------------------------------------------------------------------ commands
def cmd_maps(settings: dict, args) -> int:
    maps = list_maps(_game_dir(settings))
    if not maps:
        print("Keine Karten gefunden. Steam-Installation nicht erkannt? Setze game_dir in", config.SETTINGS_FILE)
        return 1
    print(f"{len(maps)} Karten in {_game_dir(settings)}:")
    for m in maps:
        starts = ",".join(str(n) for n in sorted(m.starts))
        print(f"  {m.key:30s} {m.name:35s} {m.size[0]}x{m.size[1]:<5d} Mex {len(m.mass):3d} Hydro {len(m.hydro):2d} Starts {starts}")
    return 0


def cmd_screenshot(settings: dict, args) -> int:
    from .game import Game

    win.set_dpi_aware()
    game = Game(settings, GameFiles(_game_dir(settings)))
    if not game.attach():
        print("Spielfenster nicht gefunden.")
        return 1
    img = game.screenshot()
    p = config.DEBUG_DIR / f"screenshot_{int(time.time())}.png"
    game.capture.save(img, p)
    print("Gespeichert:", p, img.shape)
    return 0


def cmd_test_input(settings: dict, args) -> int:
    from .inputs import Inputs

    win.set_dpi_aware()
    inp = Inputs(dry_run=False)
    print("Bewege die Maus in 3 Sekunden in einem Quadrat (bitte nichts beruehren) ...")
    time.sleep(3)
    x, y = win.cursor_pos()
    for dx, dy in ((100, 0), (100, 100), (0, 100), (0, 0)):
        inp.move(x + dx, y + dy)
        time.sleep(0.3)
    print("Fertig. Hat sich die Maus bewegt? Dann funktioniert SendInput.")
    return 0


def cmd_layouts(settings: dict, args) -> int:
    if args.clear:
        print(f"{layouts.clear_all()} Layout-Dateien geloescht.")
        return 0
    files = sorted(config.LAYOUTS_DIR.glob("*.json"))
    if not files:
        print("Keine gespeicherten Layouts.")
    for f in files:
        data = layouts.load_map_layouts(f.stem)
        for sk, rec in data.items():
            print(f"  {f.stem:30s} Start {sk:12s} Siege {rec.get('wins', 0)} Niederl. {rec.get('losses', 0)} Slots {len(rec.get('entries', []))}")
    return 0


def cmd_reports(settings: dict, args) -> int:
    from . import report

    files = report.list_reports()
    if not files:
        print("Keine Spielberichte in", report.GAMES_DIR)
        return 0
    import json

    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {d.get('time')}  {d.get('map'):28s} {d.get('result'):7s} {d.get('game_seconds', 0) // 60:3d} min  {d.get('strategy')}  Wellen {len(d.get('waves', []))}")
            if args.last and f is files[0] and d.get("debrief"):
                print("\n" + d["debrief"] + "\n")
        except Exception:
            print("  ", f.name)
    return 0


def cmd_doctor(settings: dict, args) -> int:
    """First-run diagnosis: modules, game files, window, UI recognition on the live screen."""
    import importlib
    import platform

    ok, warn = "  OK   ", "  WARN "
    print(f"SupComBot doctor  (Python {platform.python_version()}, {platform.system()} {platform.release()})")
    print(f"{ok}Einstellungen: {config.SETTINGS_FILE}")
    for mod, why in (("numpy", "Pflicht"), ("PIL", "Pflicht"), ("mss", "Pflicht"), ("keyboard", "Hotkeys"), ("cv2", "schnellere Bildanalyse (optional)"), ("dxcam", "schnelleres Capture (optional)")):
        try:
            importlib.import_module(mod)
            print(f"{ok}Modul {mod}")
        except Exception as exc:
            print(f"{warn}Modul {mod} fehlt ({why}): {exc}")
    gd = _game_dir(settings)
    files = GameFiles(gd)
    maps = list_maps(gd)
    print(f"{ok if maps else warn}Spielordner: {gd}  Karten: {len(maps)}")
    for arc, path, what in (("textures.scd", "textures/ui/common/icons/units/ueb0101_icon.dds", "Baumenue-Icons"),
                            ("units.scd", "units/ueb0101/ueb0101_unit.bp", "Blueprints"),
                            ("lua.scd", "lua/keymap/defaultKeyMap.lua", "Tastenbelegung")):
        data = files.read(arc, path) if files.available() else None
        print(f"{ok if data else warn}{arc}: {what} " + ("lesbar" if data else "NICHT lesbar"))
    icon = files.unit_icon("ueb0101")
    print(f"{ok if icon is not None else warn}Icon-Dekodierung (DDS): " + (f"{icon.shape[1]}x{icon.shape[0]}" if icon is not None else "fehlgeschlagen"))
    km = files.keymap()
    if km:
        print(f"{ok}Spiel-Tasten: attack={km.get('attack')} patrol={km.get('patrol')} select_commander={km.get('select_commander')} goto_commander={km.get('goto_commander')}")
    else:
        print(f"{warn}Keine Tastenbelegung gelesen (Angriff dann per Alt+Rechtsklick, ACU per Klick)")
    if not win.IS_WINDOWS:
        print(f"{warn}Kein Windows: Spielfenster/Eingaben nicht pruefbar")
        return 0
    from .game import Game

    win.set_dpi_aware()
    game = Game(settings, files)
    if not game.attach():
        print(f"{warn}Spielfenster nicht gefunden (Titel enthaelt '{settings.get('window_title')}'?). Spiel starten, dann doctor erneut.")
        return 0
    w, h = game.client_size
    print(f"{ok}Spielfenster: {win.window_title(game.hwnd)}  Client {w}x{h}")
    print("       Waehle jetzt im Spiel den ACU an (Baumenue sichtbar) und zoome ganz heraus ... 4 s")
    time.sleep(4)
    frame = game.screenshot()
    eco = game.ui.read_economy(frame)
    print(f"{ok if eco.mass is not None else warn}Wirtschaftsleisten: Masse {eco.mass_bar} Energie {eco.energy_bar}")
    scale = game.ui.detect_scale(frame)
    print(f"{ok if scale else warn}UI-Skalierung: {scale}")
    from . import uef

    panel = game.ui.read_panel(frame, uef.T1_ENGINEER_BUILDS) if scale else None
    if panel and panel.items:
        print(f"{ok}Baumenue erkannt: " + ", ".join(f"{uef.display_name(k)}@{v}" for k, v in panel.items.items()))
    else:
        print(f"{warn}Baumenue nicht erkannt (ist der ACU ausgewaehlt?)")
    idle = game.ui.idle_engineer(frame) if scale else None
    print(f"{ok if idle else warn}Idle-Ingenieur-Button: {idle or 'nicht sichtbar (normal, wenn kein Ingenieur untaetig ist)'}")
    from . import vision

    rect = vision.detect_map_rect(frame, game.ui.exclude_rects(w, h))
    print(f"{ok if rect else warn}Kartenrechteck: {rect}")
    if rect and maps:
        from .capture import crop

        best, score = match_map(crop(frame, rect), maps)
        print(f"{ok if best else warn}Karte erkannt: {best.name if best else '-'} ({score:.2f})")
    out = config.DEBUG_DIR / "doctor.png"
    _annotate(frame, panel, eco, rect, idle, game.ui, out)
    print(f"       Kontrollbild: {out}")
    adv = _advisor(settings)
    print(f"{ok if adv.check() else warn}Ollama: " + (f"Modell {adv.model}" if adv.available else adv.last_error))
    return 0


def _annotate(frame, panel, eco, rect, idle, ui, out: Path) -> None:
    try:
        from PIL import Image, ImageDraw

        im = Image.fromarray(frame)
        d = ImageDraw.Draw(im)
        if panel:
            for bp, (x, y) in panel.items.items():
                r = panel.slot // 2
                d.rectangle([x - r, y - r, x + r, y + r], outline=(0, 255, 0), width=2)
                d.text((x - r, y - r - 12), bp, fill=(255, 255, 0))
            for tier in (1, 2, 3):
                pos = ui.tab_position(tier)
                if pos:
                    d.ellipse([pos[0] - 6, pos[1] - 6, pos[0] + 6, pos[1] + 6], outline=(255, 0, 255), width=2)
        for bar, col in ((eco.mass_bar, (0, 255, 0)), (eco.energy_bar, (255, 160, 0))):
            if bar:
                x, length, y = bar
                d.rectangle([x, y - 3, x + length, y + 3], outline=col, width=1)
        if rect:
            d.rectangle([rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]], outline=(255, 0, 0), width=2)
        if idle:
            d.ellipse([idle[0] - 10, idle[1] - 10, idle[0] + 10, idle[1] + 10], outline=(255, 255, 0), width=2)
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(str(out))
    except Exception as exc:
        print("Kontrollbild fehlgeschlagen:", exc)


def cmd_run(settings: dict, args) -> int:
    from .bot import Bot
    from .game import Game
    from .overlay import Overlay
    from . import vision

    log = logmod.get()
    win.set_dpi_aware()
    if args.dry_run:
        settings.setdefault("advanced", {})["dry_run"] = True
    gd = _game_dir(settings)
    maps = list_maps(gd)
    if not maps:
        print("Keine Karten gefunden. Steam-Installation nicht erkannt? Setze game_dir in", config.SETTINGS_FILE)
        return 1
    files = GameFiles(gd)
    if files.unit_icon("ueb0101") is None:
        log.warning("Baumenue-Icons aus %s nicht lesbar - der Bot kann das Baumenue nicht erkennen. `doctor` ausfuehren.", gd / "gamedata" / "textures.scd")
    game = Game(settings, files)
    print("Warte auf das Spielfenster (Spiel starten, Skirmish laden) ... Strg+C bricht ab.")
    while not game.attach():
        if config.adv(settings, "dry_run"):
            break
        time.sleep(1.5)

    chosen = None
    wanted = args.map or str(settings.get("map") or "").strip()
    if wanted.lower() == "auto":
        wanted = ""
    if wanted:
        chosen = find_map(maps, wanted)
        if not chosen:
            print("Karte nicht gefunden:", wanted, "- versuche automatische Erkennung.")
    if not chosen and game.hwnd:
        print("Karte wird erkannt: bitte im Spiel ganz herauszoomen ... (5 s)")
        time.sleep(5)
        img = game.screenshot()
        w, h = game.client_size
        rect = vision.detect_map_rect(img, game.ui.exclude_rects(w, h))
        if rect:
            from .capture import crop

            chosen, score = match_map(crop(img, rect), maps)
            print(f"Erkannt: {chosen.name if chosen else '-'} ({score:.2f})")
            if chosen and score < 0.35:
                print("Unsichere Erkennung. Starte mit --map <name>, wenn das falsch ist.")
    if not chosen:
        chosen = maps[0]
        print("Karte konnte nicht erkannt werden, nutze", chosen.name, "- besser: start.bat --map <name>")

    advisor = _make_advisor(settings, log)
    bot = Bot(settings, game, chosen, advisor)
    bot.start()

    def quit_all() -> None:
        bot.stop()
        config.save_settings(settings)
        overlay.close()

    overlay = Overlay(settings, bot, quit_all)
    print("Overlay laeuft. Bot mit", settings["hotkeys"]["toggle_bot"], "einschalten. Beenden mit", settings["hotkeys"]["quit"])
    try:
        overlay.run()
    finally:
        bot.stop()
        settings["bot_enabled"] = False
        config.save_settings(settings)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="supcombot", description="SupComBot - externer UEF-Bot fuer Supreme Commander: Forged Alliance (Steam)")
    parser.add_argument("--debug", action="store_true", help="ausfuehrliches Log + Debug-Screenshots")
    sub = parser.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="Bot + Overlay starten (Standard)")
    p_run.add_argument("--map", help="Kartenname/-ordner statt Auto-Erkennung")
    p_run.add_argument("--dry-run", action="store_true", help="keine Eingaben senden, nur planen/loggen")
    sub.add_parser("doctor", help="Erstdiagnose: Module, Spieldateien, Fenster, UI-Erkennung")
    sub.add_parser("maps", help="gefundene Karten auflisten")
    sub.add_parser("screenshot", help="Screenshot des Spielfensters speichern")
    sub.add_parser("test-input", help="Mausbewegung per SendInput testen")
    p_lay = sub.add_parser("layouts", help="gespeicherte Layouts anzeigen")
    p_lay.add_argument("--clear", action="store_true")
    p_rep = sub.add_parser("reports", help="Spielberichte anzeigen")
    p_rep.add_argument("--last", action="store_true", help="Nachbesprechung des letzten Spiels ausgeben")
    args = parser.parse_args(argv)

    settings = config.load_settings()
    settings["bot_enabled"] = False
    if args.debug:
        settings.setdefault("advanced", {})["debug"] = True
    logmod.setup(bool(config.adv(settings, "debug")))
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "map"):
        args = parser.parse_args(["run"] + (["--debug"] if args.debug else []))
    handlers = {"run": cmd_run, "doctor": cmd_doctor, "maps": cmd_maps, "screenshot": cmd_screenshot,
                "test-input": cmd_test_input, "layouts": cmd_layouts, "reports": cmd_reports}
    try:
        return handlers[cmd](settings, args)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
