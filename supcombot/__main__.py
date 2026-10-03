"""Command line entry point: python -m supcombot <command>."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config, layouts, log as logmod, win
from .maps import find_map, list_maps, match_map, steam_game_dir


def _game_dir(settings: dict):
    gd = settings.get("game_dir")
    return Path(gd) if gd else steam_game_dir()


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


def cmd_detect_map(settings: dict, args) -> int:
    from .game import Game
    from .profile import Profile
    from .capture import crop
    from . import vision

    win.set_dpi_aware()
    game = Game(settings, Profile(settings["faction"], (1, 1)))
    if not game.attach():
        print("Spielfenster nicht gefunden.")
        return 1
    game.profile = Profile.load(settings["faction"], game.client_size)
    print("Zoome im Spiel ganz heraus; Screenshot in 3 Sekunden ...")
    time.sleep(3)
    img = game.screenshot()
    rect = vision.detect_map_rect(img, game.profile.exclude_rects())
    print("Kartenrechteck:", rect)
    if not rect:
        return 1
    maps = list_maps(_game_dir(settings))
    best, score = match_map(crop(img, rect), maps)
    print(f"Beste Uebereinstimmung: {best.name if best else '-'} ({score:.2f})")
    return 0


def cmd_ollama(settings: dict, args) -> int:
    from .ollama import OllamaAdvisor

    o = settings["ollama"]
    adv = OllamaAdvisor(o["url"], o["model"], o.get("timeout", 60), o.get("language", "de"))
    if not adv.check():
        print(adv.last_error)
        return 1
    print("Modelle:", ", ".join(adv.list_models()))
    print("Teste Anfrage mit Beispielzustand ...")
    state = {"t": 420, "phase": "expand", "strategy": "balanced", "mass": {"ratio": 0.04, "stall": True}, "energy": {"ratio": 0.7},
             "structures": {"mex": 5, "pgen": 4, "landFac": 2}, "units": {"armyEstimate": 9}}
    res = adv.ask(state, ["[06:40] Angriffswelle 1: ~12 Einheiten", "[07:00] Mass-Stall"])
    print("Antwort:", res if res else adv.last_raw[:300])
    return 0 if res else 1


def cmd_calibrate(settings: dict, args) -> int:
    from .calibrate import capture_template, run_wizard

    faction = args.faction or settings["faction"]
    if args.template:
        capture_template(settings, faction, args.template)
        return 0
    run_wizard(settings, faction, only=args.only, map_rect_only=args.map_rect)
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


def cmd_screenshot(settings: dict, args) -> int:
    from .game import Game
    from .profile import Profile

    win.set_dpi_aware()
    game = Game(settings, Profile(settings["faction"], (1, 1)))
    if not game.attach():
        print("Spielfenster nicht gefunden.")
        return 1
    img = game.screenshot()
    p = config.DEBUG_DIR / f"screenshot_{int(time.time())}.png"
    game.capture.save(img, p)
    print("Gespeichert:", p, img.shape)
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


def cmd_run(settings: dict, args) -> int:
    from .bot import Bot
    from .game import Game
    from .ollama import OllamaAdvisor
    from .overlay import Overlay
    from .profile import Profile
    from .capture import crop
    from . import vision

    log = logmod.get()
    win.set_dpi_aware()
    if args.dry_run:
        settings["dry_run"] = True
    maps = list_maps(_game_dir(settings))
    if not maps:
        print("Keine Karten gefunden. Setze game_dir in", config.SETTINGS_FILE)
        return 1

    game = Game(settings, Profile(settings["faction"], (1, 1)))
    print("Warte auf das Spielfenster (Spiel starten, Skirmish laden) ... Strg+C bricht ab.")
    while not game.attach():
        if settings.get("dry_run"):
            break
        time.sleep(1.5)
    res = game.client_size if game.hwnd else (1920, 1080)
    game.profile = Profile.load(settings["faction"], res)
    missing = game.profile.missing_required()
    if missing and not args.force:
        print(f"Profil {settings['faction']} {res[0]}x{res[1]} ist nicht kalibriert. Fehlend: {', '.join(missing)}")
        print("Bitte zuerst: python -m supcombot calibrate")
        return 1

    # Map selection: explicit, otherwise auto-detect from the full zoom-out view.
    chosen = None
    if args.map or settings.get("map", "auto") != "auto":
        chosen = find_map(maps, args.map or settings["map"])
        if not chosen:
            print("Karte nicht gefunden:", args.map or settings["map"])
            return 1
    else:
        if game.hwnd:
            print("Karte wird erkannt: bitte im Spiel ganz herauszoomen ... (5 s)")
            time.sleep(5)
            img = game.screenshot()
            rect = vision.detect_map_rect(img, game.profile.exclude_rects())
            if rect:
                chosen, score = match_map(crop(img, rect), maps)
                print(f"Erkannt: {chosen.name if chosen else '-'} ({score:.2f})")
                if chosen and score < 0.35:
                    print("Unsichere Erkennung. Starte mit --map <name>, wenn das falsch ist.")
        if not chosen:
            chosen = maps[0]
            print("Karte konnte nicht erkannt werden, nutze", chosen.name, "- besser: --map <name>")
    if int(settings.get("start_slot", 1)) not in chosen.starts:
        settings["start_slot"] = sorted(chosen.starts)[0] if chosen.starts else 1

    advisor = None
    if settings.get("use_ollama"):
        o = settings["ollama"]
        advisor = OllamaAdvisor(o["url"], o["model"], o.get("timeout", 60), o.get("language", "de"))
        if not advisor.check():
            log.warning("Ollama deaktiviert: %s", advisor.last_error)

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
        config.save_settings(settings)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="supcombot", description="SupComBot - externer Bot fuer Supreme Commander: Forged Alliance (Steam)")
    parser.add_argument("--debug", action="store_true", help="ausfuehrliches Log + Debug-Screenshots")
    sub = parser.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="Bot + Overlay starten (Standard)")
    p_run.add_argument("--map", help="Kartenname/-ordner statt Auto-Erkennung")
    p_run.add_argument("--dry-run", action="store_true", help="keine Eingaben senden, nur planen/loggen")
    p_run.add_argument("--force", action="store_true", help="auch mit unvollstaendigem Profil starten")
    p_cal = sub.add_parser("calibrate", help="UI-Positionen kalibrieren")
    p_cal.add_argument("--faction", choices=config.FACTIONS)
    p_cal.add_argument("--only", nargs="*", help="nur diese Schluessel neu kalibrieren")
    p_cal.add_argument("--map-rect", action="store_true", help="nur das Kartenrechteck")
    p_cal.add_argument("--template", choices=["victory", "defeat"], help="Sieg-/Niederlage-Dialog als Vorlage aufnehmen")
    sub.add_parser("maps", help="gefundene Karten auflisten")
    sub.add_parser("detect-map", help="aktuelle Karte per Screenshot erkennen")
    sub.add_parser("ollama-test", help="Ollama-Verbindung testen")
    sub.add_parser("test-input", help="Mausbewegung per SendInput testen")
    sub.add_parser("screenshot", help="Screenshot des Spielfensters speichern")
    p_lay = sub.add_parser("layouts", help="gespeicherte Layouts anzeigen")
    p_lay.add_argument("--clear", action="store_true")
    args = parser.parse_args(argv)

    settings = config.load_settings()
    if args.debug:
        settings["debug"] = True
    logmod.setup(settings.get("debug", False))
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "map"):
        args = parser.parse_args(["run"] + (["--debug"] if args.debug else []))
    handlers = {
        "run": cmd_run, "calibrate": cmd_calibrate, "maps": cmd_maps, "detect-map": cmd_detect_map,
        "ollama-test": cmd_ollama, "test-input": cmd_test_input, "screenshot": cmd_screenshot, "layouts": cmd_layouts,
    }
    try:
        return handlers[cmd](settings, args)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
