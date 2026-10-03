"""Camera handling: the bot works at full zoom-out where the whole map is visible and
world coordinates map linearly onto the detected map rectangle."""
from __future__ import annotations

import time
from typing import Optional, Tuple

from . import vision
from .game import Game
from .log import get
from .maps import MapInfo

log = get("camera")


class CalibrationError(RuntimeError):
    pass


class Camera:
    def __init__(self, game: Game, map_info: MapInfo) -> None:
        self.game = game
        self.map = map_info
        self.rect: Optional[Tuple[int, int, int, int]] = None
        self.last_zoom = 0.0
        self.detect_failures = 0
        stored = game.profile.map_rects.get(map_info.key)
        if stored:
            self.rect = tuple(stored)  # type: ignore[assignment]

    # ------------------------------------------------------------------ zoom
    def zoom_out_fully(self) -> None:
        notches = int(self.game.settings.get("input", {}).get("zoom_out_notches", 40))
        self.game.wheel(-notches)
        self.game.wait(self.game.settings.get("input", {}).get("settle_after_zoom", 0.6))
        self.last_zoom = time.time()

    def ensure_strategic(self, redetect: bool = True) -> Tuple[int, int, int, int]:
        """Zoom out and (re)detect the map rectangle. Falls back to the stored rectangle."""
        self.zoom_out_fully()
        if redetect:
            img = self.game.screenshot()
            rect = vision.detect_map_rect(img, self.game.profile.exclude_rects(), expected_aspect=self.map.aspect)
            if rect and self._plausible(rect):
                if self.rect is None or self._differs(rect, self.rect):
                    log.info("Kartenrechteck erkannt: %s", rect)
                    self.game.profile.map_rects[self.map.key] = list(rect)
                    self.game.profile.save()
                self.rect = rect
                self.detect_failures = 0
            else:
                self.detect_failures += 1
                if self.rect is None:
                    self.game.save_debug(img, "maprect_fail")
                    raise CalibrationError("Kartenrechteck nicht erkannt. Bitte `python -m supcombot calibrate --map-rect` ausfuehren.")
                if self.detect_failures in (1, 10):
                    log.warning("Kartenrechteck nicht erkannt (%d), nutze gespeichertes %s", self.detect_failures, self.rect)
        if self.rect is None:
            raise CalibrationError("Kein Kartenrechteck bekannt.")
        return self.rect

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
        precision = int(self.game.settings.get("input", {}).get("precision_zoom_notches", 0))
        if precision > 0:
            # Zoom-to-cursor keeps the hovered world point under the cursor: zoom in for a precise click.
            self.game.wheel(precision, (cx, cy))
            self.game.wait(0.35)
            self.game.click(cx, cy, button=button, shift=shift, modifier=modifier)
            self.zoom_out_fully()
        else:
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
