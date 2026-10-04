"""Image analysis on numpy RGB arrays. OpenCV is used when installed, pure numpy otherwise."""
from __future__ import annotations

from collections import deque
from typing import Iterable, List, Optional, Sequence, Tuple

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
    if img.ndim == 2:
        return img.astype(np.float32)
    return (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]).astype(np.float32)


def resize(img: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.fromarray(img).resize(size, Image.LANCZOS))


def mask_rects(img: np.ndarray, rects: Iterable[Rect]) -> np.ndarray:
    out = img.copy()
    for x, y, w, h in rects:
        out[max(0, y):y + h, max(0, x):x + w] = 0
    return out


def crop(img: np.ndarray, rect: Rect) -> np.ndarray:
    x, y, w, h = rect
    h_img, w_img = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + w), min(h_img, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return img[y0:y1, x0:x1]


# ------------------------------------------------------------------------------------------ map rectangle
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


# ------------------------------------------------------------------------------------------ bars / colours
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


def color_mask(img: np.ndarray, color: Sequence[int], tol: int = 40) -> np.ndarray:
    c = np.array(color, dtype=np.int16)
    d = np.abs(img.astype(np.int16) - c).sum(axis=2)
    return d <= tol


def mass_bar_mask(img: np.ndarray) -> np.ndarray:
    """Bright green of the mass storage bar in the economy panel."""
    r, g, b = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    return (g > 170) & (r < 215) & (b < 120) & (g - b > 90) & (g - r > 25)


def energy_bar_mask(img: np.ndarray) -> np.ndarray:
    """Bright orange of the energy storage bar."""
    r, g, b = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    return (r > 200) & (g > 120) & (g < 215) & (b < 120) & (r - b > 110) & (r - g > 35)


def longest_run(row: np.ndarray) -> Tuple[int, int]:
    """(start, length) of the longest run of True values in a 1-D bool array."""
    best_s, best_l, s, l = 0, 0, 0, 0
    for i, v in enumerate(row):
        if v:
            if l == 0:
                s = i
            l += 1
            if l > best_l:
                best_s, best_l = s, l
        else:
            l = 0
    return best_s, best_l


def find_bar(mask: np.ndarray, min_len: int = 12) -> Optional[Tuple[int, int, int]]:
    """Longest horizontal run of mask pixels: (x_start, length, y). Picks the row with the longest run."""
    best = None
    rows = np.where(mask.sum(axis=1) >= min_len)[0]
    for y in rows:
        s, l = longest_run(mask[y])
        if l >= min_len and (best is None or l > best[1]):
            best = (int(s), int(l), int(y))
    return best


def red_green_balance(img: np.ndarray) -> float:
    """+1 .. -1: share of green minus share of red pixels in a region (sign of the income number)."""
    r, g, b = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    green = int(((g > 90) & (g > r + 15) & (g > b + 30)).sum())
    red = int(((r > 90) & (r > g + 40) & (r > b + 40)).sum())
    tot = green + red
    if tot < 4:
        return 0.0
    return (green - red) / tot


# ------------------------------------------------------------------------------------------ patches
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


def match_template_at(img: np.ndarray, template: np.ndarray, x: int, y: int, search: int = 6) -> float:
    """Best similarity of template around (x, y) +- search pixels (cheap local search)."""
    best = 0.0
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 2):
            best = max(best, patch_similarity(img, template, x + dx, y + dy))
    return best


def normalized_correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = gray(a) if a.ndim == 3 else a.astype(np.float32)
    b = gray(b) if b.ndim == 3 else b.astype(np.float32)
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom == 0:
        return 0.0
    return float((a * b).sum() / denom)


# ------------------------------------------------------------------------------------------ template matching (NCC)
def _integral(a: np.ndarray) -> np.ndarray:
    s = np.cumsum(np.cumsum(a, axis=0), axis=1)
    out = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
    out[1:, 1:] = s
    return out


def _window_sums(integ: np.ndarray, h: int, w: int) -> np.ndarray:
    return integ[h:, w:] - integ[:-h, w:] - integ[h:, :-w] + integ[:-h, :-w]


def ncc_map(img: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Zero-mean normalized cross-correlation of a 2-D float template over a 2-D float image.

    Returns an array of shape (H-h+1, W-w+1) with values in [-1, 1].
    """
    img = img.astype(np.float32)
    tpl = tpl.astype(np.float32)
    H, W = img.shape
    h, w = tpl.shape
    if h > H or w > W or h < 2 or w < 2:
        return np.full((max(1, H - h + 1), max(1, W - w + 1)), -1.0, dtype=np.float32)
    if HAS_CV2:
        return cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    t0 = tpl - tpl.mean()
    tn = float(np.sqrt((t0 * t0).sum()))
    if tn < 1e-6:
        return np.zeros((H - h + 1, W - w + 1), dtype=np.float32)
    fh, fw = H + h - 1, W + w - 1
    F = np.fft.rfft2(img, s=(fh, fw))
    T = np.fft.rfft2(t0[::-1, ::-1], s=(fh, fw))
    corr = np.fft.irfft2(F * T, s=(fh, fw))[h - 1:H, w - 1:W]
    n = float(h * w)
    integ = _integral(img.astype(np.float64))
    integ2 = _integral((img.astype(np.float64)) ** 2)
    s1 = _window_sums(integ, h, w)
    s2 = _window_sums(integ2, h, w)
    var = s2 - (s1 * s1) / n
    std = np.sqrt(np.maximum(var, 1e-6))
    out = corr / (std * tn)
    return np.clip(out, -1.0, 1.0).astype(np.float32)


def ncc_map_rgb(img: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Average NCC over the three colour channels (more selective than grayscale for coloured icons)."""
    if img.ndim == 2 or tpl.ndim == 2:
        return ncc_map(gray(img), gray(tpl))
    acc = None
    for c in range(3):
        m = ncc_map(img[:, :, c], tpl[:, :, c])
        acc = m if acc is None else acc + m
    return acc / 3.0


def best_match(img: np.ndarray, tpl: np.ndarray) -> Tuple[float, int, int]:
    """(score, x, y) of the best template position; x, y = top-left corner inside img."""
    m = ncc_map_rgb(img, tpl)
    idx = int(np.argmax(m))
    y, x = divmod(idx, m.shape[1])
    return float(m[y, x]), int(x), int(y)


def all_matches(img: np.ndarray, tpl: np.ndarray, threshold: float, min_dist: Optional[int] = None) -> List[Tuple[float, int, int]]:
    """All local maxima >= threshold as (score, x, y) sorted by score, suppressing neighbours within min_dist."""
    m = ncc_map_rgb(img, tpl)
    h, w = tpl.shape[:2]
    if min_dist is None:
        min_dist = max(4, min(h, w) // 2)
    cand = np.argwhere(m >= threshold)
    scored = sorted(((float(m[y, x]), int(x), int(y)) for y, x in cand), reverse=True)
    out: List[Tuple[float, int, int]] = []
    for s, x, y in scored:
        if all(abs(x - ox) >= min_dist or abs(y - oy) >= min_dist for _s, ox, oy in out):
            out.append((s, x, y))
            if len(out) >= 64:
                break
    return out


def composite_over(rgba: np.ndarray, bg: Sequence[int]) -> np.ndarray:
    """Alpha-composite an RGBA image over a flat background colour; returns RGB uint8."""
    if rgba.shape[2] == 3:
        return rgba.astype(np.uint8)
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    rgb = rgba[:, :, :3].astype(np.float32)
    b = np.array(bg, dtype=np.float32).reshape(1, 1, 3)
    return np.clip(rgb * a + b * (1 - a), 0, 255).astype(np.uint8)


def tint(rgba: np.ndarray, color: Sequence[int], bg: Sequence[int] = (30, 30, 30)) -> np.ndarray:
    """Tint a greyscale strategic icon with a team colour the way the game does and flatten it onto bg."""
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    col = np.array(color, dtype=np.float32).reshape(1, 1, 3)
    tinted = np.concatenate([np.clip(rgb * col, 0, 255), rgba[:, :, 3:4].astype(np.float32)], axis=2)
    return composite_over(tinted, bg)


# ------------------------------------------------------------------------------------------ blobs
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
    return len(blob_centroids(mask, min_pixels, max_blobs))


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


def whiteness(img: np.ndarray, min_value: int = 215) -> int:
    """Number of near-white pixels (selection brackets around a strategic icon)."""
    return int((img.min(axis=2) >= min_value).sum())


def dominant_color(img: np.ndarray, min_saturation: int = 60) -> Optional[List[int]]:
    """Most common saturated colour in a small region (team colour of a strategic icon)."""
    px = img.reshape(-1, 3).astype(np.int16)
    sat = px.max(axis=1) - px.min(axis=1)
    px = px[sat >= min_saturation]
    if len(px) < 3:
        return None
    q = (px // 24) * 24 + 12
    keys, counts = np.unique(q, axis=0, return_counts=True)
    best = keys[int(np.argmax(counts))]
    sel = px[np.all(q == best, axis=1)]
    return [int(v) for v in sel.mean(axis=0)]
