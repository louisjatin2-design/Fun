"""Live vision: a continuous frame stream of the game window plus a perception thread.

The stream keeps the latest frame in memory (dxcam / Desktop Duplication when available, mss otherwise),
so the bot and the overlay never wait for a screenshot. Perception analyses frames several times per second
and publishes `Percepts`: economy, idle buttons, army at the rally, enemies on the map, UI visibility.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from . import vision
from .capture import Capture, crop
from .log import get

log = get("vision")


class FrameStream(threading.Thread):
    def __init__(self, game, fps: float = 20.0, backend: str = "auto") -> None:
        super().__init__(name="supcombot-frames", daemon=True)
        self.game = game
        self.fps = max(1.0, float(fps))
        self.backend_wanted = backend
        self.backend = "none"
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._new = threading.Event()
        self._frame: Optional[np.ndarray] = None
        self._ts = 0.0
        self.measured_fps = 0.0
        self.frames = 0
        self._cam = None
        self._capture: Optional[Capture] = None

    # ------------------------------------------------------------------ backends
    def _init_backend(self) -> None:
        if self.backend_wanted in ("auto", "dxcam"):
            try:
                import dxcam  # type: ignore

                self._cam = dxcam.create(output_color="RGB")
                self.backend = "dxcam"
                log.info("Live-Sicht: dxcam (Desktop Duplication)")
                return
            except Exception as exc:
                log.info("dxcam nicht verfuegbar (%s), nutze mss", exc)
        try:
            self._capture = Capture()
            self.backend = "mss"
            log.info("Live-Sicht: mss mit %.0f fps", self.fps)
        except Exception as exc:
            log.warning("Keine Bildquelle: %s", exc)
            self.backend = "none"

    def _grab(self) -> Optional[np.ndarray]:
        left, top, w, h = self.game.rect
        if w <= 0 or h <= 0:
            return None
        if self._cam is not None:
            try:
                frame = self._cam.grab(region=(left, top, left + w, top + h))
                return None if frame is None else np.ascontiguousarray(frame)
            except Exception as exc:
                log.warning("dxcam-Fehler (%s), wechsle auf mss", exc)
                self._cam = None
                self._capture = Capture()
                self.backend = "mss"
        if self._capture is not None:
            return self._capture.grab((left, top, w, h))
        return None

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        self._init_backend()
        period = 1.0 / self.fps
        window_start, window_frames = time.time(), 0
        last_rect = 0.0
        while not self.stop_event.is_set():
            t0 = time.time()
            if not self.game.hwnd:
                if not self.game.attach():
                    time.sleep(0.5)
                    continue
            if t0 - last_rect > 1.0:
                self.game.refresh_rect()
                last_rect = t0
            frame = None
            try:
                frame = self._grab()
            except Exception as exc:
                log.debug("grab fehlgeschlagen: %s", exc)
            if frame is not None:
                with self._lock:
                    self._frame, self._ts = frame, t0
                self._new.set()
                self.frames += 1
                window_frames += 1
            if t0 - window_start >= 1.0:
                self.measured_fps = window_frames / (t0 - window_start)
                window_start, window_frames = t0, 0
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)
        if self._cam is not None:
            try:
                self._cam.release()
            except Exception:
                pass

    # ------------------------------------------------------------------ access
    def latest(self, max_age: Optional[float] = None) -> Tuple[Optional[np.ndarray], float]:
        with self._lock:
            frame, ts = self._frame, self._ts
        if frame is None or (max_age is not None and time.time() - ts > max_age):
            return None, ts
        return frame, ts

    def wait_new(self, timeout: float = 0.5) -> Tuple[Optional[np.ndarray], float]:
        self._new.clear()
        self._new.wait(timeout)
        return self.latest()

    def stop(self) -> None:
        self.stop_event.set()


@dataclass
class Percepts:
    ts: float = 0.0
    mass: Optional[float] = None
    energy: Optional[float] = None
    mass_income: float = 0.0
    energy_income: float = 0.0
    ui_visible: bool = False                 # economy panel found: we are in a running game
    idle_engineer: Optional[Tuple[int, int]] = None
    idle_factory: Optional[Tuple[int, int]] = None
    map_view_valid: bool = False
    army_seen: Optional[int] = None
    enemies_near_base: int = 0
    enemy_world: Optional[Tuple[float, float]] = None
    enemy_points: List[Tuple[int, int]] = field(default_factory=list)   # client coords for the preview
    enemy_clusters: List[Tuple[float, float, int]] = field(default_factory=list)  # world x, z, icon count
    enemies_total: int = 0
    friendly_clusters: List[Tuple[float, float, int]] = field(default_factory=list)
    friendly_total: int = 0
    analysis_ms: float = 0.0
    fps: float = 0.0
    backend: str = "none"


class Perception(threading.Thread):
    """Analyses the live stream a few times per second and publishes Percepts."""

    def __init__(self, stream: FrameStream, game, camera, ctx, state, hz: float = 5.0, base_radius: float = 60.0) -> None:
        super().__init__(name="supcombot-perception", daemon=True)
        self.stream = stream
        self.game = game
        self.camera = camera
        self.ctx = ctx
        self.state = state
        self.hz = max(0.5, float(hz))
        self.base_radius = base_radius
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._percepts = Percepts()
        self._last_rect_check = 0.0
        self._last_avatar_check = 0.0
        self._map_view_valid = False
        self._idle_eng: Optional[Tuple[int, int]] = None
        self._idle_fac: Optional[Tuple[int, int]] = None

    def percepts(self) -> Percepts:
        with self._lock:
            return self._percepts

    def run(self) -> None:
        period = 1.0 / self.hz
        while not self.stop_event.is_set():
            t0 = time.time()
            frame, ts = self.stream.latest(max_age=2.0)
            if frame is not None:
                try:
                    p = self.analyze(frame, ts)
                    with self._lock:
                        self._percepts = p
                except Exception as exc:  # perception must never die
                    log.debug("Wahrnehmung fehlgeschlagen: %s", exc)
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)

    def stop(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------ analysis (pure, testable)
    def analyze(self, frame: np.ndarray, ts: float) -> Percepts:
        ui = self.game.ui
        p = Percepts(ts=ts, fps=self.stream.measured_fps, backend=self.stream.backend)
        t_start = time.time()

        eco = ui.read_economy(frame)
        p.mass, p.energy = eco.mass, eco.energy
        p.mass_income, p.energy_income = eco.mass_income, eco.energy_income
        p.ui_visible = eco.mass is not None

        # Idle buttons (template search in the avatar column) at most twice per second.
        if ts - self._last_avatar_check > 0.5 and ui.scale is not None:
            self._last_avatar_check = ts
            self._idle_eng = ui.idle_engineer(frame)
            self._idle_fac = ui.idle_factory(frame)
        p.idle_engineer, p.idle_factory = self._idle_eng, self._idle_fac

        # Map based percepts only when the strategic view is on screen.
        if ts - self._last_rect_check > 1.0 and self.camera.rect is not None:
            self._last_rect_check = ts
            w, h = self.game.client_size
            rect = vision.detect_map_rect(frame, ui.exclude_rects(w, h), expected_aspect=self.camera.map.aspect)
            self._map_view_valid = bool(rect) and not Camera_differs(rect, self.camera.rect)
        p.map_view_valid = self._map_view_valid and self.camera.rect is not None
        if not p.map_view_valid:
            p.analysis_ms = (time.time() - t_start) * 1000
            return p

        team = self.state.team_color
        if team:
            region = crop(frame, self.camera.world_rect_to_client(self.ctx.rally[0], self.ctx.rally[1], 28))
            p.army_seen = vision.count_blobs(vision.color_mask(region, team, tol=60), min_pixels=2, max_blobs=300)
            p.friendly_clusters, p.friendly_total = self._clusters(frame, [team], self.camera.rect)

        enemy_colors = self.state.enemy_colors or []
        if enemy_colors:
            p.enemy_clusters, p.enemies_total, p.enemy_points = self._clusters(frame, enemy_colors, self.camera.rect, with_points=True)
            near = [(x, z, n) for x, z, n in p.enemy_clusters
                    if (x - self.ctx.start[0]) ** 2 + (z - self.ctx.start[1]) ** 2 <= self.base_radius ** 2]
            p.enemies_near_base = int(sum(n for _x, _z, n in near))
            if near:
                p.enemy_world = (near[0][0], near[0][1])
        p.analysis_ms = (time.time() - t_start) * 1000
        return p

    def _clusters(self, frame, colors, rect, with_points: bool = False):
        """Icon blobs of the given colours inside rect (client coords) -> world clusters [(x, z, count)]."""
        rx, ry, rw, rh = rect
        region = crop(frame, (rx, ry, rw, rh))
        mask = np.zeros(region.shape[:2], dtype=bool)
        for c in colors:
            mask |= vision.color_mask(region, c, tol=55)
        blobs = vision.blob_centroids(mask, min_pixels=2, max_blobs=1500)
        upp = self.camera.units_per_pixel()
        world_pts = []
        for x, y, _a in blobs:
            wx, wz = self.camera.client_to_world(int(rx + x), int(ry + y))
            world_pts.append((wx, wz, 1.0))
        clusters = [(x, z, int(n)) for x, z, n in vision.cluster_points(world_pts, radius=max(24.0, 12.0 * upp))]
        if with_points:
            return clusters, len(blobs), [(rx + int(x), ry + int(y)) for x, y, _a in blobs[:400]]
        return clusters, len(blobs)


def Camera_differs(a, b, tol: int = 8) -> bool:
    return any(abs(int(a[i]) - int(b[i])) > tol for i in range(4))
