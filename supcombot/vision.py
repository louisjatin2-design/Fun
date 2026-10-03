"""Image analysis helpers on numpy RGB arrays (no OpenCV needed)."""
from __future__ import annotations

from collections import deque
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2  # type: ignore

    HAS_CV2 = True
except Exception:  # pragma: no cover - optional accelerator
    cv2 = None
    HAS_CV2 = False

Rect = Tuple[int, int, int, int]  # x, y, w, h


def set_threads(n: int) -> None:
    if HAS_CV2:
        try:
            cv2.setNumThreads(int(n))
        except Exception:
            pass


def gray(img: np.ndarray) -> np.ndarray:
    return (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]).astype(np.float32)


def resize(img: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.fromarray(img).resize(size, Image.BILINEAR))


def mask_rects(img: np.ndarray, rects: Iterable[Rect]) -> np.ndarray:
    out = img.copy()
    for x, y, w, h in rects:
        out[max(0, y):y + h, max(0, x):x + w] = 0
    return out


def detect_map_rect(img: np.ndarray, exclude: Sequence[Rect] = (), threshold: float = 16.0,
                    expected_aspect: Optional[float] = None) -> Optional[Rect]:
    """Bounding box of the non-black map area at full zoom-out.

    Rows/columns inside `exclude` (UI panels) are ignored. Row/column is "lit" when at least 2% of its
    pixels are brighter than threshold. With `expected_aspect` (w/h) the result is sanity checked.
    """
    g = gray(mask_rects(img, exclude))
    lit = g > threshold
    h, w = lit.shape
    col_frac = lit.sum(axis=0) / max(1, h)
    row_frac = lit.sum(axis=1) / max(1, w)
    cols = np.where(col_frac > 0.02)[0]
    rows = np.where(row_frac > 0.02)[0]
    if len(cols) < 10 or len(rows) < 10:
        return None
    x0, x1 = int(cols[0]), int(cols[-1])
    y0, y1 = int(rows[0]), int(rows[-1])
    rect = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    if expected_aspect:
        aspect = rect[2] / max(1, rect[3])
        if abs(aspect - expected_aspect) / expected_aspect > 0.12:
            # UI contamination likely: trust the smaller dimension and derive the other one, centered.
            if aspect > expected_aspect:
                new_w = int(rect[3] * expected_aspect)
                cx = x0 + rect[2] / 2
                rect = (int(cx - new_w / 2), y0, new_w, rect[3])
            else:
                new_h = int(rect[2] / expected_aspect)
                cy = y0 + rect[3] / 2
                rect = (x0, int(cy - new_h / 2), rect[2], new_h)
    return rect


def bar_fill_ratio(img: np.ndarray, x1: int, x2: int, y: int, min_brightness: float = 70.0, band: int = 2) -> float:
    """Fraction of a horizontal bar (x1..x2 at row y) that is 'lit'. Scans a small vertical band."""
    h, w = img.shape[:2]
    if x2 <= x1 or not (0 <= y < h):
        return 0.0
    y0, y1 = max(0, y - band), min(h, y + band + 1)
    strip = gray(img[y0:y1, max(0, x1):min(w, x2)])
    if strip.size == 0:
        return 0.0
    lit = (strip.max(axis=0) > min_brightness)
    # The fill grows from the left; find the last lit column of the longest leading run.
    n = len(lit)
    filled = 0
    gap = 0
    for i in range(n):
        if lit[i]:
            filled = i + 1
            gap = 0
        else:
            gap += 1
            if gap > 3 and filled > 0:
                break
    return float(filled) / float(n)


def patch_similarity(img: np.ndarray, patch: np.ndarray, x: int, y: int) -> float:
    """1.0 = identical. Compares `patch` with the region of `img` centered at (x, y)."""
    ph, pw = patch.shape[:2]
    x0, y0 = x - pw // 2, y - ph // 2
    h, w = img.shape[:2]
    if x0 < 0 or y0 < 0 or x0 + pw > w or y0 + ph > h:
        return 0.0
    region = img[y0:y0 + ph, x0:x0 + pw].astype(np.int16)
    diff = np.abs(region - patch.astype(np.int16)).mean()
    return max(0.0, 1.0 - diff / 128.0)


def extract_patch(img: np.ndarray, x: int, y: int, size: int = 24) -> np.ndarray:
    h, w = img.shape[:2]
    half = size // 2
    x0, y0 = max(0, x - half), max(0, y - half)
    x1, y1 = min(w, x0 + size), min(h, y0 + size)
    return np.ascontiguousarray(img[y0:y1, x0:x1])


def color_mask(img: np.ndarray, color: Sequence[int], tol: int = 40) -> np.ndarray:
    c = np.array(color, dtype=np.int16)
    d = np.abs(img.astype(np.int16) - c).sum(axis=2)
    return d <= tol


def blob_centroids(mask: np.ndarray, min_pixels: int = 3, max_blobs: int = 2000):
    """Centroids [(x, y, area), ...] of connected components. OpenCV when available, numpy BFS otherwise."""
    if HAS_CV2:
        n, _labels, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=4)
        out = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= min_pixels:
                out.append((float(cents[i][0]), float(cents[i][1]), area))
                if len(out) >= max_blobs:
                    break
        return out
    return _blob_centroids_py(mask, min_pixels, max_blobs)


def _blob_centroids_py(mask: np.ndarray, min_pixels: int, max_blobs: int):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.where(mask)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        q = deque([(sy, sx)])
        seen[sy, sx] = True
        pts = []
        while q:
            y, x = q.popleft()
            pts.append((x, y))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(pts) >= min_pixels:
            out.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), len(pts)))
            if len(out) >= max_blobs:
                break
    return out


def count_blobs(mask: np.ndarray, min_pixels: int = 3, max_blobs: int = 500) -> int:
    """Number of connected components (4-neighbourhood) with at least min_pixels."""
    if HAS_CV2:
        return len(blob_centroids(mask, min_pixels, max_blobs))
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    count = 0
    ys, xs = np.where(mask)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        q = deque([(sy, sx)])
        seen[sy, sx] = True
        size = 0
        while q:
            y, x = q.popleft()
            size += 1
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if size >= min_pixels:
            count += 1
            if count >= max_blobs:
                break
    return count


def cluster_points(points, radius: float):
    """Greedy clustering of (x, y, weight) points: returns [(x, y, total_weight), ...]."""
    clusters = []
    for x, y, w in points:
        for c in clusters:
            if (c[0] - x) ** 2 + (c[1] - y) ** 2 <= radius * radius:
                tw = c[2] + w
                c[0] = (c[0] * c[2] + x * w) / tw
                c[1] = (c[1] * c[2] + y * w) / tw
                c[2] = tw
                break
        else:
            clusters.append([float(x), float(y), float(w)])
    clusters.sort(key=lambda c: -c[2])
    return [(c[0], c[1], c[2]) for c in clusters]


def placement_verdict(frame: np.ndarray, cx: int, cy: int, radius: int = 10, min_pixels: int = 6) -> str:
    """Colour of the build preview under the cursor: 'ok' (green), 'blocked' (red) or 'unknown'."""
    h, w = frame.shape[:2]
    x0, y0 = max(0, cx - radius), max(0, cy - radius)
    x1, y1 = min(w, cx + radius + 1), min(h, cy + radius + 1)
    if x1 <= x0 or y1 <= y0:
        return "unknown"
    region = frame[y0:y1, x0:x1].astype(np.int16)
    r, g, b = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    red = int(((r > 140) & (g < 90) & (b < 90) & (r - g > 70)).sum())
    green = int(((g > 140) & (r < 120) & (b < 120) & (g - r > 60)).sum())
    if red >= min_pixels and red > green * 1.5:
        return "blocked"
    if green >= min_pixels and green >= red:
        return "ok"
    return "unknown"


def normalized_correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = gray(a) if a.ndim == 3 else a.astype(np.float32)
    b = gray(b) if b.ndim == 3 else b.astype(np.float32)
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom == 0:
        return 0.0
    return float((a * b).sum() / denom)


def match_template_at(img: np.ndarray, template: np.ndarray, x: int, y: int, search: int = 6) -> float:
    """Best similarity of template around (x, y) +- search pixels (cheap local search)."""
    best = 0.0
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 2):
            best = max(best, patch_similarity(img, template, x + dx, y + dy))
    return best
