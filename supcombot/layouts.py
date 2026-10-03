"""Per map / start position layout memory (JSON files in %APPDATA%/SupComBot/layouts)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from . import config
from .log import get

log = get("layouts")


def _path(map_key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in map_key)
    return config.LAYOUTS_DIR / f"{safe}.json"


def load_map_layouts(map_key: str) -> dict:
    p = _path(map_key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def load(map_key: str, start_key: str) -> Optional[dict]:
    rec = load_map_layouts(map_key).get(start_key)
    if rec and rec.get("entries"):
        return rec
    return None


def merge_entries(old: List[dict], new: List[dict], cap: int = 200) -> List[dict]:
    out: List[dict] = []
    seen = set()
    for lst in (new, old or []):
        for e in lst:
            try:
                k = (e["role"], round(float(e["dx"])), round(float(e["dz"])))
            except (KeyError, TypeError, ValueError):
                continue
            if k in seen or len(out) >= cap:
                continue
            seen.add(k)
            out.append({"role": e["role"], "dx": float(e["dx"]), "dz": float(e["dz"])})
    return out


def store_result(map_key: str, start_key: str, won: bool, entries: List[dict], extra: Optional[dict] = None) -> dict:
    """Won: merge the layout in and reset losses. Lost twice in a row: forget it and start fresh."""
    config.ensure_dirs()
    all_recs = load_map_layouts(map_key)
    rec = all_recs.get(start_key) or {"wins": 0, "losses": 0, "entries": []}
    if won:
        rec["wins"] = rec.get("wins", 0) + 1
        rec["losses"] = 0
        rec["entries"] = merge_entries(rec.get("entries", []), entries)
        rec["last_win"] = time.time()
    else:
        rec["losses"] = rec.get("losses", 0) + 1
        if rec["losses"] >= 2:
            rec["entries"] = []
            rec["wins"] = 0
    if extra:
        strategy = extra.pop("strategy", None)
        rec.update(extra)
        if strategy:
            stats = rec.setdefault("strategy_stats", {}).setdefault(strategy, {"wins": 0, "losses": 0})
            stats["wins" if won else "losses"] += 1
    all_recs[start_key] = rec
    _path(map_key).write_text(json.dumps(all_recs, indent=1), encoding="utf-8")
    log.info("Layout gespeichert: %s / %s (won=%s, %d Eintraege)", map_key, start_key, won, len(rec["entries"]))
    return rec


def clear_all() -> int:
    n = 0
    for p in config.LAYOUTS_DIR.glob("*.json"):
        p.unlink()
        n += 1
    return n


def start_key(x: float, z: float) -> str:
    return f"{int(round(x))}_{int(round(z))}"


def best_strategy(map_key: str, start_key: str, default: str = "balanced") -> str:
    """Strategy with the best smoothed win rate on this map/start (used for strategy "auto")."""
    rec = load_map_layouts(map_key).get(start_key) or {}
    stats = rec.get("strategy_stats") or {}
    best, best_rate = default, -1.0
    for strat, st in stats.items():
        rate = (st.get("wins", 0) + 1) / (st.get("wins", 0) + st.get("losses", 0) + 2)
        if rate > best_rate:
            best, best_rate = strat, rate
    return best
