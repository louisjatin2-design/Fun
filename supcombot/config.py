"""Paths, default settings and settings persistence."""
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

PROFILES_DIR = APP_DIR / "profiles"
LAYOUTS_DIR = APP_DIR / "layouts"
LOG_DIR = APP_DIR / "logs"
DEBUG_DIR = APP_DIR / "debug"
SETTINGS_FILE = APP_DIR / "settings.json"

FACTIONS = ["uef", "aeon", "cybran", "seraphim"]
STRATEGIES = ["balanced", "eco", "rush", "turtle"]

DEFAULT_SETTINGS: dict = {
    # Game / environment
    "game_dir": "",                     # empty = auto detect Steam install
    "window_title": "Forged Alliance",  # substring of the game window title
    "faction": "uef",
    "map": "auto",                      # "auto" = detect via map preview, otherwise map folder name
    "start_slot": 1,                    # ARMY_<n> marker you spawn on (lobby slot)
    "enemy_slots": [],                  # lobby slots of enemies; empty = every other slot that is not an ally
    "ally_slots": [],                   # lobby slots of allies (team games): never attacked, not counted as enemies
    # Managers (all toggleable in the overlay)
    "bot_enabled": False,
    "auto_attack": False,
    "auto_defense": True,               # react to enemy-coloured icons near the base (needs colors.enemy)
    "build_manager": True,
    "production_manager": True,
    "eco_manager": True,
    "use_ollama": True,
    "use_layout_memory": True,
    "show_overlay": True,
    # Strategy
    "strategy": "balanced",
    "aggression": 2,                    # 1 passive, 2 normal, 3 aggressive
    "max_engineers": 12,
    "attack_threshold": 18,             # estimated army units at the rally before an auto attack
    "loop_interval": 3.0,
    # Ollama
    "ollama": {
        "url": "http://localhost:11434",
        "model": "auto",                # auto = first installed model from `prefer`, else any
        "prefer": ["qwen2.5:14b", "qwen2.5-coder:14b", "llama3.1:8b", "qwen2.5:7b", "mistral", "gemma2", "llama3", "phi"],
        "interval": 20,                 # seconds between advice requests
        "language": "de",
        "timeout": 60,
        "num_ctx": 8192,                # context window (VRAM permitting)
        "num_gpu": 99,                  # offload all layers to the GPU
        "num_thread": 0,                # 0 = let Ollama decide (CPU fallback)
    },
    # Global hotkeys (python 'keyboard' syntax)
    "hotkeys": {
        "toggle_bot": "ctrl+alt+b",
        "toggle_attack": "ctrl+alt+a",
        "attack_now": "ctrl+alt+x",
        "toggle_overlay": "alt+f6",
        "cycle_strategy": "ctrl+alt+s",
        "report_win": "ctrl+alt+w",
        "report_loss": "ctrl+alt+l",
        "new_game": "ctrl+alt+n",
        "quit": "ctrl+alt+q",
    },
    # Input timing
    "input": {
        "attack_move_modifier": "alt",  # alt + right click = attack move in FA
        "click_delay": 0.08,
        "action_delay": 0.25,
        "zoom_out_notches": 40,
        "precision_zoom_notches": 0,    # >0: zoom in at the cursor before precise clicks (large maps)
        "settle_after_zoom": 0.6,
    },
    "overlay": {"x": 20, "y": 120, "alpha": 0.88},
    # Live vision: continuous capture of the game window instead of on-demand screenshots
    "vision": {
        "fps": 60,                      # capture rate of the frame stream
        "backend": "auto",              # auto | dxcam | mss
        "perception_hz": 15,            # how often the frames are analysed
        "scan_whole_map": True,         # enemy colours on the whole map (needs colors.enemy)
        "preview": False,               # open the "Bot-Sicht" window at start
        "preview_width": 640,
    },
    # Hardware usage: "max" (default, e.g. 3080 + 5900X) or "low" for weak machines
    "performance": {"profile": "max", "threads": 0},
    "debug": False,
    "dry_run": False,
}


LOW_PROFILE = {"vision": {"fps": 15, "perception_hz": 4, "scan_whole_map": False, "preview_width": 480},
               "ollama": {"interval": 60, "num_ctx": 4096}}


def apply_performance_profile(settings: dict) -> dict:
    """Lower rates for weak machines; "max" keeps the defaults, which already target a strong PC."""
    if settings.get("performance", {}).get("profile") == "low":
        _merge(settings, copy.deepcopy(LOW_PROFILE))
    return settings


def cpu_threads(settings: dict) -> int:
    n = int(settings.get("performance", {}).get("threads", 0) or 0)
    if n <= 0:
        n = max(2, (os.cpu_count() or 4) - 2)   # leave two threads for the game
    return n


def ensure_dirs() -> None:
    for d in (APP_DIR, PROFILES_DIR, LAYOUTS_DIR, LOG_DIR, DEBUG_DIR):
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
            _merge(settings, json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    ensure_dirs()
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
