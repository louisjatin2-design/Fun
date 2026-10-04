"""Camera handling: the bot works at full zoom-out where the whole map is visible and
world coordinates map linearly onto the detected map rectangle."""
from __future__ import annotations

import time
from typing import Optional, Tuple

from . import vision
from .log import get
from .maps import MapInfo

log = get("camera")


class CalibrationError(RuntimeError):
    pass


class Camera:
    def __init__(self, game, map_info: MapInfo) -> None:
        self.game = game
        self.map = map_info
        self.rect: Optional[Tuple[int, int, int, int]] = None
        self.last_zoom = 0.0
        self.detect_failures = 0
        self.last_detect = 0.0

    # ------------------------------------------------------------------ zoom
    def zoom_out_fully(self) -> None:
        notches = int(self.game.adv("zoom_out_notches", 30))
        self.game.wheel(-notches)
        self.game.wait(0.5)
        self.last_zoom = time.time()

    def ensure_strategic(self, redetect: bool = True) -> Tuple[int, int, int, int]:
        """Zoom out and (re)detect the map rectangle. Falls back to the last known rectangle."""
        self.zoom_out_fully()
        if redetect or self.rect is None:
            img = self.game.screenshot()
            self.detect(img, strict=self.rect is None)
        if self.rect is None:
            raise CalibrationError("Kein Kartenrechteck bekannt.")
        return self.rect

    def detect(self, img, strict: bool = False) -> bool:
        w, h = self.game.client_size
        rect = vision.detect_map_rect(img, self.game.ui.exclude_rects(w, h), expected_aspect=self.map.aspect)
        self.last_detect = time.time()
        if rect and self._plausible(rect):
            if self.rect is None or self._differs(rect, self.rect):
                log.info("Kartenrechteck erkannt: %s", rect)
            self.rect = rect
            self.detect_failures = 0
            return True
        self.detect_failures += 1
        if strict:
            self.game.save_debug(img, "maprect_fail")
            raise CalibrationError("Kartenrechteck nicht erkannt: bitte im Spiel ganz herauszoomen (Mausrad).")
        if self.detect_failures in (1, 10, 50):
            log.warning("Kartenrechteck nicht erkannt (%d), nutze gespeichertes %s", self.detect_failures, self.rect)
        return False

    def _plausible(self, rect: Tuple[int, int, int, int]) -> bool:
        w, h = self.game.client_size
        x, y, rw, rh = rect
        return rw > w * 0.3 and rh > h * 0.3 and rw <= w and rh <= h and x >= -2 and y >= -2

    @staticmethod
    def _differs(a, b, tol: int = 6) -> bool:
        return any(abs(int(a[i]) - int(b[i])) > tol for i in range(4))

    # ------------------------------------------------------------------ mapping
    def world_to_client(self, x: float, z: float) -> Tuple[int, int]:
        if self.rect is None:
            raise CalibrationError("Kartenrechteck unbekannt")
        rx, ry, rw, rh = self.rect
        return int(round(rx + x / self.map.size[0] * rw)), int(round(ry + z / self.map.size[1] * rh))

    def client_to_world(self, cx: int, cy: int) -> Tuple[float, float]:
        if self.rect is None:
            raise CalibrationError("Kartenrechteck unbekannt")
        rx, ry, rw, rh = self.rect
        return (cx - rx) / max(1, rw) * self.map.size[0], (cy - ry) / max(1, rh) * self.map.size[1]

    def units_per_pixel(self) -> float:
        if self.rect is None:
            return 1.0
        return self.map.size[0] / max(1, self.rect[2])

    # ------------------------------------------------------------------ world actions
    def click_world(self, x: float, z: float, button: str = "left", shift: bool = False, modifier: Optional[str] = None) -> None:
        cx, cy = self.world_to_client(x, z)
        self.game.click(cx, cy, button=button, shift=shift, modifier=modifier)

    def hover_world(self, x: float, z: float) -> None:
        self.game.hover(*self.world_to_client(x, z))

    def box_select_world(self, cx: float, cz: float, radius: float) -> None:
        x1, y1 = self.world_to_client(cx - radius, cz - radius)
        x2, y2 = self.world_to_client(cx + radius, cz + radius)
        if x2 - x1 < 6:
            x1, x2 = x1 - 3, x2 + 3
        if y2 - y1 < 6:
            y1, y2 = y1 - 3, y2 + 3
        self.game.drag(x1, y1, x2, y2)

    def world_rect_to_client(self, cx: float, cz: float, radius: float) -> Tuple[int, int, int, int]:
        x1, y1 = self.world_to_client(cx - radius, cz - radius)
        x2, y2 = self.world_to_client(cx + radius, cz + radius)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)
