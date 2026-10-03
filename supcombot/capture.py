"""Screen capture of the game client area (mss)."""
from __future__ import annotations

from typing import Tuple

import numpy as np

try:
    import mss  # type: ignore
except Exception:  # pragma: no cover - mss is Windows/desktop only in practice
    mss = None


class Capture:
    def __init__(self) -> None:
        self._sct = mss.mss() if mss else None

    def grab(self, rect: Tuple[int, int, int, int]) -> np.ndarray:
        """Grab (left, top, width, height) in screen coordinates. Returns HxWx3 uint8 RGB."""
        if not self._sct:
            raise RuntimeError("mss ist nicht installiert (pip install mss).")
        left, top, width, height = rect
        shot = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(arr[:, :, [2, 1, 0]])

    def save(self, img: np.ndarray, path) -> None:
        from PIL import Image

        Image.fromarray(img).save(str(path))


def crop(img: np.ndarray, rect: Tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = rect
    h_img, w_img = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + w), min(h_img, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return img[y0:y1, x0:x1]
