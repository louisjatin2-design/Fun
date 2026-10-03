"""Interactive calibration wizard: records button positions, reference patches, bars, team color, map rectangle."""
from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from . import config, vision, win
from .game import Game
from .log import get
from .maps import MapInfo, list_maps, match_map, steam_game_dir
from .profile import CALIBRATION_STEPS, Profile

log = get("calibrate")

try:
    import keyboard  # type: ignore
except Exception:  # pragma: no cover
    keyboard = None

CONFIRM, SKIP, ABORT = "f8", "f7", "f6"


def _wait_key() -> str:
    """Block until F8 (confirm), F7 (skip) or F6 (abort) is pressed. Returns the key name."""
    if not keyboard:
        raise RuntimeError("Modul 'keyboard' fehlt (pip install keyboard).")
    while True:
        ev = keyboard.read_event(suppress=False)
        if ev.event_type == "down" and ev.name in (CONFIRM, SKIP, ABORT):
            time.sleep(0.15)
            return ev.name


def _attach(settings: dict, faction: str) -> Game:
    print("Suche Spielfenster ...", end="", flush=True)
    while True:
        hwnd = win.find_window(settings.get("window_title", "Forged Alliance"))
        if hwnd:
            break
        print(".", end="", flush=True)
        time.sleep(1)
    tmp_profile = Profile(faction=faction, resolution=(1, 1))
    game = Game(settings, tmp_profile)
    game.attach()
    w, h = game.client_size
    print(f"\nSpielfenster gefunden: {w}x{h} (Client-Bereich). Fenster-Titel: {win.window_title(game.hwnd)}")
    game.profile = Profile.load(faction, (w, h))
    return game


RECAPTURE_GROUPS = [
    ("ui.build.", "Waehle den ACU (oder einen T1-Ingenieur), so dass das Baumenue T1 sichtbar ist, dann F8.", 1),
    ("ui.factory.land.", "Waehle eine LANDFABRIK (Fabrikmenue sichtbar), dann F8. F7 = ueberspringen.", 1),
    ("ui.factory.air.", "Waehle eine LUFTFABRIK, dann F8. F7 = ueberspringen.", 1),
    ("ui.upgrade", "Waehle einen T1-MASSENEXTRAKTOR, dann F8. F7 = ueberspringen.", 1),
    ("ui.idle_", "Ein Ingenieur und eine Fabrik sollen untaetig sein (Idle-Symbole rechts sichtbar), dann F8.", 1),
]


def _tier_of(key: str) -> int:
    return 3 if key.endswith("3") else 2 if key.endswith("2") else 1


def copy_profile(game: Game, source_faction: str) -> List[str]:
    """Copy another faction's profile and re-capture the faction-specific button images group by group."""
    prof = game.profile
    src = Profile.load(source_faction, prof.resolution)
    if not src.points:
        print(f"Kein Profil fuer {source_faction} {prof.resolution[0]}x{prof.resolution[1]} gefunden.")
        return []
    keys = prof.copy_from(src)
    prof.save()
    print(f"\nProfil von {source_faction} uebernommen ({len(prof.points)} Punkte). Jetzt werden die fraktionsabhaengigen"
          " Button-Bilder neu aufgenommen; die Positionen bleiben.")
    done: List[str] = []
    for prefix, instruction, tier in RECAPTURE_GROUPS:
        group = [k for k in keys if k.startswith(prefix) and _tier_of(k) == tier and not k.startswith("ui.build.tab")]
        group += [k for k in keys if prefix == "ui.build." and k.startswith("ui.build.tab")]
        group += [k for k in keys if prefix == "ui.factory.land." and k in ("ui.factory.upgrade", "ui.factory.repeat")]
        if not group:
            continue
        print(f"\n[{len(group)} Punkte] {instruction}")
        k = _wait_key()
        if k == ABORT:
            break
        if k == SKIP:
            continue
        img = game.screenshot()
        n = prof.recapture(img, group)
        done += group
        prof.save()
        print(f"  {n} Referenzbilder neu aufgenommen: {', '.join(sorted(group))}")
    remaining = [k for k in keys if k not in done and _tier_of(k) > 1]
    if remaining:
        print("\nT2/T3-Buttons werden spaeter mit --only neu aufgenommen, sobald eine T2/T3-Einheit ausgewaehlt ist:")
        print("  " + " ".join(sorted(remaining)))
    return done


def run_wizard(settings: dict, faction: str, only: Optional[List[str]] = None, map_rect_only: bool = False,
               copy_from: Optional[str] = None) -> None:
    win.set_dpi_aware()
    game = _attach(settings, faction)
    prof = game.profile
    print("\n=== SupComBot Kalibrierung ===")
    print("F8 = Position uebernehmen, F7 = Schritt ueberspringen (nur optionale), F6 = abbrechen.")
    print("Das Spiel muss im Fenster-/Borderless-Modus laufen und im Vordergrund sein, wenn du F8 drueckst.\n")

    if copy_from:
        copy_profile(game, copy_from)
        missing = prof.missing_required()
        prof.calibrated = not missing
        prof.save()
        print("\nProfil gespeichert:", Profile.path_for(prof.faction, prof.resolution))
        if missing:
            print("Es fehlen noch Pflicht-Punkte:", ", ".join(missing), "-> python -m supcombot calibrate --only ...")
        else:
            print("Fertig. Kontrolle: python -m supcombot doctor")
        return

    if not map_rect_only:
        for key, instruction, want_patch, required in CALIBRATION_STEPS:
            if only and key not in only:
                continue
            tag = "PFLICHT" if required else "optional"
            print(f"\n[{tag}] {key}\n  {instruction}")
            if prof.has(key):
                print(f"  (bereits kalibriert: {prof.point(key)}; F7 behaelt den Wert)")
            k = _wait_key()
            if k == ABORT:
                print("Abgebrochen. Bisherige Werte sind gespeichert.")
                prof.save()
                return
            if k == SKIP:
                print("  uebersprungen")
                continue
            sx, sy = win.cursor_pos()
            cx, cy = game.to_client(sx, sy)
            img = game.screenshot()
            if key in ("colors.team", "colors.enemy"):
                region = img[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2].reshape(-1, 3)
                color = [int(v) for v in region.mean(axis=0)]
                if key == "colors.team":
                    prof.team_color = color
                    print(f"  Teamfarbe RGB={color}")
                else:
                    if color not in prof.enemy_colors:
                        prof.enemy_colors.append(color)
                    print(f"  Gegnerfarbe RGB={color} (gesamt {len(prof.enemy_colors)})")
            else:
                patch = vision.extract_patch(img, cx, cy, 24) if want_patch else None
                prof.set_point(key, cx, cy, patch)
                print(f"  gespeichert: ({cx}, {cy})" + (" + Referenzbild" if want_patch else ""))
            prof.save()

    # Map rectangle at full zoom-out.
    print("\n[Karte] Zoome im Spiel GANZ heraus (Mausrad), so dass die komplette Karte sichtbar ist, dann F8 (F7 = ueberspringen).")
    k = _wait_key()
    if k == CONFIRM:
        game.refresh_rect()
        img = game.screenshot()
        maps = list_maps(_game_dir(settings))
        current = _pick_map(settings, maps, img, prof)
        if current:
            rect = vision.detect_map_rect(img, prof.exclude_rects(), expected_aspect=current.aspect)
            if rect:
                prof.map_rects[current.key] = list(rect)
                print(f"  Kartenrechteck fuer {current.name}: {rect} (Client-Koordinaten)")
                _save_rect_debug(img, rect, current.key)
            else:
                print("  Kartenrechteck NICHT erkannt. Manuell: zeige auf die OBERE LINKE Ecke der Karte, F8")
                if _wait_key() == CONFIRM:
                    a = game.to_client(*win.cursor_pos())
                    print("  jetzt auf die UNTERE RECHTE Ecke, F8")
                    if _wait_key() == CONFIRM:
                        b = game.to_client(*win.cursor_pos())
                        rect = (a[0], a[1], b[0] - a[0], b[1] - a[1])
                        prof.map_rects[current.key] = list(rect)
                        print(f"  Kartenrechteck manuell: {rect}")
            prof.save()

    missing = prof.missing_required()
    prof.calibrated = not missing
    prof.save()
    print("\nProfil gespeichert:", Profile.path_for(prof.faction, prof.resolution))
    if missing:
        print("Es fehlen noch Pflicht-Punkte:", ", ".join(missing))
        print("Erneut ausfuehren mit: python -m supcombot calibrate --only " + " ".join(missing))
    else:
        print("Kalibrierung vollstaendig. Starten mit: python -m supcombot run")


def capture_template(settings: dict, faction: str, name: str, width: int = 320, height: int = 140) -> None:
    """Capture a template (e.g. the victory/defeat dialog) around the mouse cursor with F8."""
    win.set_dpi_aware()
    game = _attach(settings, faction)
    print(f"\nZeige mit der Maus auf die MITTE des '{name}'-Dialogs/Elements und druecke F8 (F6 = abbrechen).")
    if _wait_key() != CONFIRM:
        return
    cx, cy = game.to_client(*win.cursor_pos())
    img = game.screenshot()
    x0, y0 = max(0, cx - width // 2), max(0, cy - height // 2)
    patch = np.ascontiguousarray(img[y0:y0 + height, x0:x0 + width])
    game.profile.set_template(name, patch, cx, cy)
    game.profile.save()
    print(f"Template '{name}' gespeichert ({patch.shape[1]}x{patch.shape[0]} bei {cx},{cy}).")


def _game_dir(settings: dict):
    from pathlib import Path

    gd = settings.get("game_dir")
    return Path(gd) if gd else steam_game_dir()


def _pick_map(settings: dict, maps: List[MapInfo], img: np.ndarray, prof: Profile) -> Optional[MapInfo]:
    if not maps:
        print("  Keine Karten gefunden (game_dir in settings.json setzen?).")
        return None
    guess, score = None, 0.0
    rect = vision.detect_map_rect(img, prof.exclude_rects())
    if rect:
        from .capture import crop

        guess, score = match_map(crop(img, rect), maps)
    print("  Karten:")
    for i, m in enumerate(maps):
        mark = "  <- erkannt (%.2f)" % score if guess is m else ""
        print(f"   {i + 1:3d}. {m.name} ({m.size[0]}x{m.size[1]}, {len(m.mass)} Mex){mark}")
    default = maps.index(guess) + 1 if guess else 1
    raw = input(f"  Nummer der aktuellen Karte [{default}]: ").strip()
    try:
        idx = int(raw) if raw else default
        return maps[idx - 1]
    except (ValueError, IndexError):
        return None


def _save_rect_debug(img: np.ndarray, rect, key: str) -> None:
    try:
        from PIL import Image, ImageDraw

        im = Image.fromarray(img)
        d = ImageDraw.Draw(im)
        x, y, w, h = rect
        d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=3)
        p = config.DEBUG_DIR / f"maprect_{key}.png"
        im.save(str(p))
        print(f"  Kontrollbild: {p}")
    except Exception as exc:
        log.debug("Debugbild fehlgeschlagen: %s", exc)
