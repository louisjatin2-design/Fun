"""Automatic UI recognition: no manual calibration.

Everything is located on the live frame:

* **Build menu** (construction panel at the bottom): every slot is identified by matching the game's own unit icon
  textures (from ``textures.scd``) with normalized cross-correlation. The UI pixel scale (48 px per slot at 100 %
  Windows scaling) is measured once from those matches.
* **Economy**: the green mass bar and the orange energy bar in the top-left panel are found by colour; the sign of the
  net income is read from the colour of the big number right of each bar.
* **Idle engineer / idle factory buttons** in the avatar column on the right: unit icon templates again.
* **Tech tabs** (I / II / III) sit at a fixed offset above the first slot.

All geometry is relative to the client area and scales with the measured UI scale, so any resolution and any Windows
DPI setting work as long as the game uses its default skin.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import uef, vision
from .gamefiles import GameFiles
from .log import get

log = get("ui")

SLOT_PX = 48            # construction panel item size at UI scale 1.0 (vanilla construction.lua)
SPACER_PX = 20          # divider between item groups
PANEL_BG = (48, 41, 30)  # dark panel behind the icons (for alpha compositing of the templates)
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)
# Tech tab buttons relative to the first slot (measured on a 2560x1440 screenshot, in slot units).
TAB_DX, TAB_DY, TAB_PITCH = 0.25, -0.29, 0.635
AVATAR_ICON_SIZES = (56, 52, 48, 44, 40, 36, 32)  # idle-engineer button icon size candidates (px at scale 1.0)


@dataclass
class Panel:
    """What the construction panel currently shows."""
    items: Dict[str, Tuple[int, int]] = field(default_factory=dict)   # blueprint id -> click position (client px)
    scores: Dict[str, float] = field(default_factory=dict)
    row_top: int = 0
    slot: int = SLOT_PX
    first_left: int = 0
    ts: float = 0.0

    def has(self, bp_id: str) -> bool:
        return bp_id.lower() in self.items

    def kind(self) -> str:
        """'builder' (structures), 'land', 'air' (factory) or 'none'."""
        ids = set(self.items)
        if ids & uef.LAND_UNIT_IDS:
            return "land"
        if ids & uef.AIR_UNIT_IDS:
            return "air"
        if any(i.startswith("ueb") for i in ids):
            return "builder"
        return "none"


@dataclass
class EconomyReading:
    mass: Optional[float] = None       # storage fill 0..1
    energy: Optional[float] = None
    mass_income: float = 0.0           # -1..1 (colour of the net income: red = negative, green = positive)
    energy_income: float = 0.0
    mass_bar: Optional[Tuple[int, int, int]] = None    # x, length, y of the lit part
    energy_bar: Optional[Tuple[int, int, int]] = None


class UIModel:
    def __init__(self, files: GameFiles) -> None:
        self.files = files
        self.scale: Optional[float] = None
        self._templates: Dict[str, np.ndarray] = {}
        self._missing: set = set()
        self.row_top: Optional[int] = None
        self.first_left: Optional[int] = None
        self.mass_full = 0
        self.energy_full = 0
        self.mass_x0: Optional[int] = None
        self.energy_x0: Optional[int] = None
        self.last_panel: Optional[Panel] = None
        self.avatar_size: Optional[int] = None
        self._last_scale_attempt = 0.0

    # ------------------------------------------------------------------ scale
    @property
    def s(self) -> float:
        return self.scale or 1.0

    @property
    def slot(self) -> int:
        return int(round(SLOT_PX * self.s))

    def px(self, v: float) -> int:
        return int(round(v * self.s))

    # ------------------------------------------------------------------ templates
    def template(self, bp_id: str, size: Optional[int] = None) -> Optional[np.ndarray]:
        """RGB template of a unit icon at the current slot size (alpha flattened onto the panel colour)."""
        size = size or self.slot
        key = f"{bp_id.lower()}@{size}"
        if key in self._templates:
            return self._templates[key]
        if bp_id.lower() in self._missing:
            return None
        rgba = self.files.unit_icon(bp_id)
        if rgba is None:
            self._missing.add(bp_id.lower())
            return None
        if rgba.shape[0] != size or rgba.shape[1] != size:
            from PIL import Image

            rgba = np.asarray(Image.fromarray(rgba, "RGBA").resize((size, size), Image.LANCZOS))
        tpl = vision.composite_over(rgba, PANEL_BG)
        self._templates[key] = tpl
        return tpl

    def icons_available(self) -> bool:
        return self.template("ueb0101") is not None

    # ------------------------------------------------------------------ build panel
    def _band(self, frame: np.ndarray, scale: float, wide: bool) -> Tuple[np.ndarray, int, int]:
        h, w = frame.shape[:2]
        slot = int(round(SLOT_PX * scale))
        if not wide and self.row_top is not None and abs(scale - self.s) < 1e-6:
            y0 = max(0, self.row_top - 6)
            y1 = min(h, self.row_top + slot + 6)
        else:
            y0 = max(0, int(h - 200 * scale))
            y1 = max(y0 + slot + 2, int(h - 20 * scale))
        x0 = int(150 * scale)
        return frame[y0:y1, x0:], x0, y0

    def detect_scale(self, frame: np.ndarray, probe_ids: Sequence[str] = ("ueb0101", "ueb1103", "ueb1101", "uel0105", "ueb0102")) -> Optional[float]:
        """Measure the UI scale from the build menu (requires an open construction panel)."""
        best_scale, best_score = None, 0.0
        for scale in SCALES:
            size = int(round(SLOT_PX * scale))
            band, _x0, _y0 = self._band(frame, scale, wide=True)
            score = 0.0
            for pid in probe_ids:
                tpl = self.template(pid, size)
                if tpl is None:
                    continue
                s, _x, _y = vision.best_match(band, tpl)
                score = max(score, s)
            log.debug("UI-Skalierung %.2f: beste Icon-Uebereinstimmung %.2f", scale, score)
            if score > best_score:
                best_scale, best_score = scale, score
        if best_scale is not None and best_score >= 0.55:
            if self.scale != best_scale:
                log.info("UI-Skalierung erkannt: %.2f (Baumenue-Icon %d px, Score %.2f)", best_scale, int(SLOT_PX * best_scale), best_score)
            self.scale = best_scale
            return best_scale
        return None

    def read_panel(self, frame: np.ndarray, candidates: Sequence[str], threshold: float = 0.6) -> Panel:
        """Identify the icons of the construction panel. Returns an empty Panel when nothing is visible."""
        panel = Panel(slot=self.slot, ts=time.time())
        if self.scale is None:
            # The scale search costs about a second: try it at most every 3 s (the panel may simply be closed).
            if time.time() - self._last_scale_attempt < 3.0:
                return panel
            self._last_scale_attempt = time.time()
            if self.detect_scale(frame) is None:
                return panel
        band, bx, by = self._band(frame, self.s, wide=False)
        found: List[Tuple[float, int, int, str]] = []
        for pid in candidates:
            tpl = self.template(pid)
            if tpl is None:
                continue
            for s, x, y in vision.all_matches(band, tpl, threshold, min_dist=self.slot // 2):
                found.append((s, bx + x, by + y, pid.lower()))
        if not found and self.row_top is not None:
            # The cached row may be stale (window moved/resized): look at the whole bottom area once.
            band, bx, by = self._band(frame, self.s, wide=True)
            for pid in candidates:
                tpl = self.template(pid)
                if tpl is None:
                    continue
                for s, x, y in vision.all_matches(band, tpl, threshold, min_dist=self.slot // 2):
                    found.append((s, bx + x, by + y, pid.lower()))
        if not found:
            return panel
        found.sort(reverse=True)
        # One id per slot and one slot per id (best score wins).
        taken_slots: List[Tuple[int, int]] = []
        for s, x, y, pid in found:
            if pid in panel.items:
                continue
            if any(abs(x - tx) < self.slot * 0.6 and abs(y - ty) < self.slot * 0.6 for tx, ty in taken_slots):
                continue
            taken_slots.append((x, y))
            panel.items[pid] = (x + self.slot // 2, y + self.slot // 2)
            panel.scores[pid] = s
        ys = sorted(y for _x, y in taken_slots)
        panel.row_top = ys[len(ys) // 2]
        panel.first_left = min(x for x, _y in taken_slots)
        self.row_top = panel.row_top
        if self.first_left is None or panel.first_left < self.first_left:
            self.first_left = panel.first_left
        self.last_panel = panel
        return panel

    def tab_position(self, tier: int) -> Optional[Tuple[int, int]]:
        """Click position of the tech tab I/II/III above the first build slot."""
        if self.row_top is None or self.first_left is None or tier not in (1, 2, 3):
            return None
        slot = self.slot
        x = self.first_left + int(round((TAB_DX + TAB_PITCH * (tier - 1)) * slot))
        y = self.row_top + int(round(TAB_DY * slot))
        return x, y

    def tab_state(self, frame: np.ndarray, tier: int) -> str:
        """'selected' (bright ring), 'enabled' (dark button) or 'unknown'."""
        pos = self.tab_position(tier)
        if pos is None:
            return "unknown"
        r = max(3, self.px(6))
        region = vision.crop(frame, (pos[0] - r, pos[1] - r, 2 * r + 1, 2 * r + 1))
        mx = int(region.max())
        if mx > 170:
            return "selected"
        if mx < 90:
            return "enabled"
        return "unknown"

    # ------------------------------------------------------------------ economy
    def read_economy(self, frame: np.ndarray) -> EconomyReading:
        h, w = frame.shape[:2]
        s = self.s
        region = frame[0:min(h, self.px(140)), 0:min(w, self.px(420))]
        out = EconomyReading()
        mb = vision.find_bar(vision.mass_bar_mask(region), min_len=self.px(8))
        eb = vision.find_bar(vision.energy_bar_mask(region), min_len=self.px(8))
        if mb:
            x, length, y = mb
            if self.mass_x0 is None or x < self.mass_x0:
                self.mass_x0 = x
            end = x + length
            self.mass_full = max(self.mass_full, end - self.mass_x0)
            out.mass_bar = (x, length, y)
            out.mass = min(1.0, (end - self.mass_x0) / max(1, self.mass_full))
            out.mass_income = self._income_sign(frame, self.mass_x0 + self.mass_full, y)
        elif self.mass_full and self.mass_x0 is not None:
            out.mass = 0.0   # bar known but nothing lit: empty storage
        if eb:
            x, length, y = eb
            if self.energy_x0 is None or x < self.energy_x0:
                self.energy_x0 = x
            end = x + length
            self.energy_full = max(self.energy_full, end - self.energy_x0)
            out.energy_bar = (x, length, y)
            out.energy = min(1.0, (end - self.energy_x0) / max(1, self.energy_full))
            out.energy_income = self._income_sign(frame, self.energy_x0 + self.energy_full, y)
        elif self.energy_full and self.energy_x0 is not None:
            out.energy = 0.0
        return out

    def _income_sign(self, frame: np.ndarray, bar_end: int, bar_y: int) -> float:
        x0 = bar_end + self.px(8)
        rect = (x0, bar_y - self.px(4), self.px(60), self.px(22))
        return vision.red_green_balance(vision.crop(frame, rect))

    def economy_visible(self, frame: np.ndarray) -> bool:
        return self.read_economy(frame).mass is not None

    # ------------------------------------------------------------------ avatar column (idle buttons)
    def _column(self, frame: np.ndarray) -> Tuple[np.ndarray, int, int]:
        h, w = frame.shape[:2]
        x0 = max(0, w - self.px(110))
        y0 = self.px(60)
        y1 = max(y0 + 10, h - self.px(160))
        return frame[y0:y1, x0:], x0, y0

    def find_avatar(self, frame: np.ndarray, bp_ids: Sequence[str], threshold: float = 0.6) -> Optional[Tuple[int, int, str, float]]:
        """Position of an avatar button showing one of the given unit icons (idle engineers / idle factories)."""
        column, cx0, cy0 = self._column(frame)
        if column.size == 0:
            return None
        sizes = [self.avatar_size] if self.avatar_size else [self.px(v) for v in AVATAR_ICON_SIZES]
        best = None
        for size in sizes:
            for pid in bp_ids:
                tpl = self.template(pid, size)
                if tpl is None:
                    continue
                s, x, y = vision.best_match(column, tpl)
                if s >= threshold and (best is None or s > best[3]):
                    best = (cx0 + x + size // 2, cy0 + y + size // 2, pid.lower(), s, size)
        if best is None:
            return None
        if self.avatar_size is None:
            self.avatar_size = best[4]
            log.info("Avatar-Symbolgroesse erkannt: %d px", best[4])
        return best[:4]

    def idle_engineer(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        r = self.find_avatar(frame, ("uel0105", "uel0208", "uel0309"))
        return (r[0], r[1]) if r else None

    def idle_factory(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        r = self.find_avatar(frame, ("ueb0101", "ueb0102", "ueb0201", "ueb0202", "ueb0301", "ueb0302"))
        return (r[0], r[1]) if r else None

    # ------------------------------------------------------------------ geometry
    def exclude_rects(self, w: int, h: int) -> List[Tuple[int, int, int, int]]:
        """UI panels to ignore when looking for the map rectangle at full zoom-out."""
        return [
            (0, 0, w, self.px(100)),                         # economy, menu, score panels
            (0, h - self.px(150), w, self.px(150)),          # orders + construction panel
            (w - self.px(95), 0, self.px(95), h),            # avatar column
            (0, 0, self.px(140), h),                         # player list / chat
        ]

    def void_point(self, w: int, h: int) -> Tuple[int, int]:
        """A spot on the map that is never covered by UI: used to deselect with a left click."""
        return (self.px(150), h // 2)

    def description(self) -> str:
        return (f"Skalierung {self.s:.2f}, Slot {self.slot}px, Reihe y={self.row_top}, Masse-Leiste {self.mass_full}px, "
                f"Energie-Leiste {self.energy_full}px, Avatar {self.avatar_size}px")
