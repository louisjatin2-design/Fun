"""Paths and the (deliberately tiny) settings file.

Everything the bot needs is detected at runtime; the settings only hold the few things you may want to change:
the hotkeys, the strategy and optional helpers (Ollama). The file is created on first start.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "SupComBot"
PACKAGE_DIR = Path(__file__).resolve().parent

if os.name == "nt":
    APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
else:  # development / tests on other platforms
    APP_DIR = Path.home() / ".supcombot"

LAYOUTS_DIR = APP_DIR / "layouts"
LOG_DIR = APP_DIR / "logs"
DEBUG_DIR = APP_DIR / "debug"
SETTINGS_FILE = APP_DIR / "settings.json"

STRATEGIES = ["auto", "balanced", "eco", "rush", "turtle"]

SETTINGS_VERSION = 2

DEFAULT_SETTINGS: dict = {
    "settings_version": SETTINGS_VERSION,
    "game_dir": "",                     # empty = Steam install is found automatically
    "window_title": "Forged Alliance",  # part of the game window title
    "strategy": "balanced",             # auto | balanced | eco | rush | turtle
    "auto_attack": True,                # send waves on its own once the army is big enough
    "attack_threshold": 16,             # estimated units at the rally point before a wave goes out
    "max_engineers": 14,
    "start_slot": 0,                    # 0 = detect at game start (ACU under the camera); otherwise the lobby slot
    "ally_slots": [],                   # lobby slots of allies in team games (never attacked)
    "hotkeys": {
        "toggle_bot": "ctrl+alt+b",
        "toggle_attack": "ctrl+alt+a",
        "attack_now": "ctrl+alt+x",
        "toggle_overlay": "alt+f6",
        "report_win": "ctrl+alt+w",
        "report_loss": "ctrl+alt+l",
        "new_game": "ctrl+alt+n",
        "quit": "ctrl+alt+q",
    },
    "ollama": {"enabled": "auto", "url": "http://localhost:11434", "model": "auto", "interval": 30},
    "overlay": {"x": 20, "y": 140, "alpha": 0.9},
    "advanced": {
        "loop_interval": 2.5,
        "yield_to_user_seconds": 4,     # pause while you move the mouse yourself (0 = off)
        "placement_check": True,        # read the green/red build preview before placing
        "zoom_out_notches": 30,
        "capture_fps": 30,
        "perception_hz": 8,
        "debug": False,
        "dry_run": False,
    },
}


def ensure_dirs() -> None:
    for d in (APP_DIR, LAYOUTS_DIR, LOG_DIR, DEBUG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def load_settings() -> dict:
    ensure_dirs()
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _merge(settings, migrate(data))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def migrate(data: dict) -> dict:
    """Settings from version 1 (calibration era) only keep what still means the same thing."""
    if int(data.get("settings_version", 1) or 1) >= SETTINGS_VERSION:
        return data
    keep = {k: data[k] for k in ("game_dir", "window_title") if data.get(k)}
    if isinstance(data.get("overlay"), dict):
        keep["overlay"] = {k: v for k, v in data["overlay"].items() if k in ("x", "y", "alpha")}
    keep["settings_version"] = SETTINGS_VERSION
    return keep


def save_settings(settings: dict) -> None:
    ensure_dirs()
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


def adv(settings: dict, key: str, default=None):
    return settings.get("advanced", {}).get(key, default)
