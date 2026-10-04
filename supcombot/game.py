"""Game controller: window, frames, low-level input and UI-level actions (select, read the build menu, click an icon)."""
from __future__ import annotations

import time
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from . import config, uef, vision, win
from .capture import Capture
from .gamefiles import GameFiles
from .inputs import Inputs
from .log import get
from .ui import Panel, UIModel

log = get("game")


class Game:
    def __init__(self, settings: dict, files: GameFiles) -> None:
        self.settings = settings
        self.files = files
        self.ui = UIModel(files)
        self.dry_run = bool(config.adv(settings, "dry_run")) or not win.IS_WINDOWS
        self.inputs = Inputs(0.08, 0.22, self.dry_run, log)
        self.capture = Capture() if win.IS_WINDOWS else None
        self.hwnd: Optional[int] = None
        self.rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._last_shot: Optional[np.ndarray] = None
        self._last_shot_time = 0.0
        self.stream = None  # FrameStream, attached by the bot
        self._debug_counter = 0
        self.keys: Dict[str, str] = {}
        try:
            self.keys = files.keymap()
        except Exception as exc:
            log.debug("Tastenbelegung nicht lesbar: %s", exc)
        if self.keys:
            log.info("Spiel-Tasten: Angriff=%s Patrouille=%s ACU=%s", self.keys.get("attack"), self.keys.get("patrol"),
                     self.keys.get("select_commander") or self.keys.get("goto_commander"))

    def adv(self, key: str, default=None):
        return config.adv(self.settings, key, default)

    # ------------------------------------------------------------------ window
    def attach(self) -> bool:
        if not win.IS_WINDOWS:
            return self.dry_run
        hwnd = win.find_window(self.settings.get("window_title", "Forged Alliance"))
        if not hwnd:
            self.hwnd = None
            return False
        if hwnd != self.hwnd:
            log.info("Spielfenster: %s", win.window_title(hwnd))
        self.hwnd = hwnd
        self.refresh_rect()
        return True

    def refresh_rect(self) -> None:
        if self.hwnd:
            try:
                self.rect = win.client_rect(self.hwnd)
            except Exception:
                self.hwnd = None

    @property
    def client_size(self) -> Tuple[int, int]:
        return self.rect[2], self.rect[3]

    def focused(self) -> bool:
        if self.dry_run and not self.hwnd:
            return True
        return bool(self.hwnd) and win.is_foreground(self.hwnd)

    # ------------------------------------------------------------------ coordinates
    def to_screen(self, cx: float, cy: float) -> Tuple[int, int]:
        return int(self.rect[0] + cx), int(self.rect[1] + cy)

    def to_client(self, sx: int, sy: int) -> Tuple[int, int]:
        return int(sx - self.rect[0]), int(sy - self.rect[1])

    def center(self) -> Tuple[int, int]:
        return self.rect[2] // 2, self.rect[3] // 2

    # ------------------------------------------------------------------ capture
    def screenshot(self, max_age: float = 0.0) -> np.ndarray:
        """Latest frame (client area, RGB). With the live stream attached this never blocks on its own capture."""
        if max_age > 0 and self._last_shot is not None and time.time() - self._last_shot_time < max_age:
            return self._last_shot
        stream = getattr(self, "stream", None)
        if stream is not None and stream.is_alive():
            frame, ts = stream.latest(max_age=0.12)
            if frame is None:
                frame, ts = stream.wait_new(0.4)
            if frame is not None:
                self._last_shot, self._last_shot_time = frame, ts
                return frame
        if not self.capture or not self.hwnd:
            img = np.zeros((self.rect[3], self.rect[2], 3), dtype=np.uint8)
        else:
            self.refresh_rect()
            img = self.capture.grab(self.rect)
        self._last_shot = img
        self._last_shot_time = time.time()
        return img

    def fresh_frame(self, settle: float = 0.25) -> np.ndarray:
        """Wait a moment for the UI to update, then grab a frame newer than that moment."""
        self.wait(settle)
        stream = getattr(self, "stream", None)
        if stream is not None and stream.is_alive():
            frame, _ts = stream.wait_new(0.4)
            if frame is not None:
                return frame
        return self.screenshot()

    def save_debug(self, img: np.ndarray, name: str) -> None:
        if not self.adv("debug"):
            return
        try:
            from PIL import Image

            self._debug_counter += 1
            Image.fromarray(img).save(str(config.DEBUG_DIR / f"{int(time.time())}_{self._debug_counter:04d}_{name}.png"))
        except Exception as exc:  # debugging must never crash the bot
            log.debug("Debug-Bild nicht gespeichert: %s", exc)

    # ------------------------------------------------------------------ low level input (client coords)
    def click(self, cx: int, cy: int, button: str = "left", shift: bool = False, modifier: Optional[str] = None) -> None:
        sx, sy = self.to_screen(cx, cy)
        self.inputs.click(sx, sy, button=button, shift=shift, modifier=modifier)

    def hover(self, cx: int, cy: int) -> None:
        self.inputs.move(*self.to_screen(cx, cy))

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        a = self.to_screen(x1, y1)
        b = self.to_screen(x2, y2)
        self.inputs.drag(a[0], a[1], b[0], b[1])

    def wheel(self, notches: int, at: Optional[Tuple[int, int]] = None) -> None:
        if at is None:
            at = self.center()
        sx, sy = self.to_screen(*at)
        self.inputs.wheel(notches, sx, sy)

    def press(self, key: str) -> None:
        self.inputs.press(key)

    def action(self, name: str) -> bool:
        """Press the key the game binds to an action (read from the game's keymap). False if unbound."""
        combo = self.keys.get(name)
        if not combo:
            return False
        ok = self.inputs.combo(combo)
        if ok:
            self.wait(0.08)
        return ok

    def wait(self, seconds: Optional[float] = None) -> None:
        self.inputs.sleep(self.inputs.action_delay if seconds is None else seconds)

    # ------------------------------------------------------------------ UI level
    def panel(self, candidates: Optional[Sequence[str]] = None, frame: Optional[np.ndarray] = None, settle: float = 0.3) -> Panel:
        """Read the construction panel. `candidates` limits the icons that are searched (faster, fewer false hits)."""
        if frame is None:
            frame = self.fresh_frame(settle)
        if candidates is None:
            candidates = list(uef.STRUCTURES.values()) + list(uef.UNITS.values())
        if self.dry_run and not self.hwnd:
            p = Panel(ts=time.time())
            for i, c in enumerate(candidates):
                p.items[c.lower()] = (300 + i * 48, self.rect[3] - 80)
            return p
        p = self.ui.read_panel(frame, candidates)
        if p.items:
            log.debug("Baumenue: %s", ", ".join(f"{uef.display_name(k)}:{p.scores[k]:.2f}" for k in p.items))
        return p

    def click_item(self, bp_id: str, panel: Optional[Panel] = None, shift: bool = False) -> bool:
        """Click a build-menu icon by blueprint id."""
        bp_id = bp_id.lower()
        if panel is None or not panel.has(bp_id):
            panel = self.panel([bp_id])
        if not panel.has(bp_id):
            log.debug("Icon %s nicht im Baumenue", uef.display_name(bp_id))
            return False
        x, y = panel.items[bp_id]
        self.click(x, y, shift=shift)
        self.wait(0.15)
        return True

    def select_tab(self, tier: int) -> bool:
        """Switch the construction panel to tech tab I/II/III."""
        pos = self.ui.tab_position(tier)
        if pos is None:
            return False
        frame = self.screenshot()
        if self.ui.tab_state(frame, tier) == "selected":
            return True
        self.click(*pos)
        self.wait(0.25)
        return True

    def deselect(self) -> None:
        """Left click on empty map space clears the selection (and leaves build mode)."""
        w, h = self.client_size
        self.click(*self.ui.void_point(w, h))
        self.wait(0.1)

    def cancel_build_mode(self) -> None:
        self.press("escape")
        self.wait(0.08)

    def attack_move(self, cx: int, cy: int) -> None:
        """Attack-move the selection to a client position: game 'attack' key + left click, else Alt+right click."""
        if self.action("attack"):
            self.click(cx, cy)
        else:
            self.click(cx, cy, button="right", modifier="alt")

    def select_commander(self) -> bool:
        return self.action("select_commander") or self.action("goto_commander")

    def economy(self, frame: Optional[np.ndarray] = None):
        return self.ui.read_economy(self.screenshot() if frame is None else frame)

    def idle_engineer_button(self, frame: Optional[np.ndarray] = None) -> Optional[Tuple[int, int]]:
        if self.dry_run and not self.hwnd:
            return None
        return self.ui.idle_engineer(self.screenshot() if frame is None else frame)

    def idle_factory_button(self, frame: Optional[np.ndarray] = None) -> Optional[Tuple[int, int]]:
        if self.dry_run and not self.hwnd:
            return None
        return self.ui.idle_factory(self.screenshot() if frame is None else frame)

    def selection_highlight(self, frame: np.ndarray, cx: int, cy: int) -> int:
        """Near-white pixel count around a map position (selected strategic icons get white brackets)."""
        r = self.ui.px(14)
        return vision.whiteness(vision.crop(frame, (cx - r, cy - r, 2 * r + 1, 2 * r + 1)))

    def icon_color(self, frame: np.ndarray, cx: int, cy: int) -> Optional[list]:
        r = self.ui.px(9)
        return vision.dominant_color(vision.crop(frame, (cx - r, cy - r, 2 * r + 1, 2 * r + 1)))
