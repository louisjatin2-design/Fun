"""GameController: window attachment, screenshots and UI-level actions (click a calibrated button, ...)."""
from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from . import config, vision, win
from .capture import Capture
from .inputs import Inputs
from .log import get
from .profile import Profile

log = get("game")


class GameNotFound(RuntimeError):
    pass


class Game:
    def __init__(self, settings: dict, profile: Profile) -> None:
        self.settings = settings
        self.profile = profile
        inp = settings.get("input", {})
        self.dry_run = bool(settings.get("dry_run")) or not win.IS_WINDOWS
        self.inputs = Inputs(inp.get("click_delay", 0.08), inp.get("action_delay", 0.25), self.dry_run, log)
        self.capture = Capture() if win.IS_WINDOWS else None
        self.hwnd: Optional[int] = None
        self.rect: Tuple[int, int, int, int] = (0, 0, profile.resolution[0], profile.resolution[1])
        self._last_shot: Optional[np.ndarray] = None
        self._last_shot_time = 0.0
        self._debug_counter = 0

    # ------------------------------------------------------------------ window
    def attach(self) -> bool:
        if not win.IS_WINDOWS:
            log.warning("Kein Windows: laufe im Dry-Run ohne Spielfenster.")
            return self.dry_run
        hwnd = win.find_window(self.settings.get("window_title", "Forged Alliance"))
        if not hwnd:
            self.hwnd = None
            return False
        self.hwnd = hwnd
        self.refresh_rect()
        return True

    def refresh_rect(self) -> None:
        if self.hwnd:
            self.rect = win.client_rect(self.hwnd)

    @property
    def client_size(self) -> Tuple[int, int]:
        return self.rect[2], self.rect[3]

    def resolution_matches_profile(self) -> bool:
        return tuple(self.client_size) == tuple(self.profile.resolution)

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
        if max_age > 0 and self._last_shot is not None and time.time() - self._last_shot_time < max_age:
            return self._last_shot
        if not self.capture or not self.hwnd:
            img = np.zeros((self.rect[3], self.rect[2], 3), dtype=np.uint8)
        else:
            self.refresh_rect()
            img = self.capture.grab(self.rect)
        self._last_shot = img
        self._last_shot_time = time.time()
        return img

    def save_debug(self, img: np.ndarray, name: str) -> None:
        if not self.settings.get("debug"):
            return
        try:
            from PIL import Image

            self._debug_counter += 1
            Image.fromarray(img).save(str(config.DEBUG_DIR / f"{int(time.time())}_{self._debug_counter:04d}_{name}.png"))
        except Exception as exc:  # debugging must never crash the bot
            log.debug("Debug-Bild nicht gespeichert: %s", exc)

    # ------------------------------------------------------------------ low level input in client coords
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

    def wait(self, seconds: Optional[float] = None) -> None:
        self.inputs.sleep(self.inputs.action_delay if seconds is None else seconds)

    # ------------------------------------------------------------------ calibrated UI
    def click_ui(self, key: str, button: str = "left", shift: bool = False) -> bool:
        if not self.profile.has(key):
            log.debug("UI-Punkt %s nicht kalibriert", key)
            return False
        x, y = self.profile.point(key)
        self.click(x, y, button=button, shift=shift)
        self.wait()
        return True

    def ui_visible(self, key: str, threshold: float = 0.78, img: Optional[np.ndarray] = None) -> bool:
        """Compare the stored reference patch with the live screen at the calibrated point."""
        patch = self.profile.patch(key)
        if patch is None or not self.profile.has(key):
            return False
        if self.dry_run and not self.hwnd:
            return True
        if img is None:
            img = self.screenshot()
        x, y = self.profile.point(key)
        return vision.match_template_at(img, patch, x, y, search=2) >= threshold

    def deselect(self, void_point: Optional[Tuple[int, int]] = None) -> None:
        """Left click on empty space clears the selection."""
        if void_point is None:
            void_point = (4, self.rect[3] // 2)
        self.click(*void_point)
        self.wait(0.1)
