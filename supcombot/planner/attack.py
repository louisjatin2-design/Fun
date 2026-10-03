"""Attack wave planning. Without unit vision the bot attacks known positions: enemy expansions, then the base."""
from __future__ import annotations

import time
from typing import Optional, Tuple

from ..state import BotState, Wave
from .builder import MapContext, dist


def threshold(state: BotState, settings: dict) -> int:
    n = int(settings.get("attack_threshold", 18))
    if state.advice and state.advice.get("attackThreshold"):
        n = int(state.advice["attackThreshold"])
    if state.strategy == "rush":
        n = int(n * 0.6)
    if state.strategy == "turtle":
        n = int(n * 1.6)
    if state.aggression == 3:
        n = int(n * 0.7)
    if state.aggression == 1:
        n = int(n * 1.4)
    return max(4, min(120, n))


def estimate_army(state: BotState) -> float:
    """Army size estimate: vision count at the rally if available, otherwise production minus losses."""
    if state.army_seen is not None:
        return float(state.army_seen)
    sent = sum(w.size for w in state.waves)
    return max(0.0, state.army_ordered * 0.9 - sent)


def pick_target(state: BotState, ctx: MapContext, from_pos: Tuple[float, float],
                seen_clusters=None, base_radius: float = 60.0) -> Optional[Tuple[float, float]]:
    """Seen enemy clusters first (live vision), then enemy mass markers on their side, then the enemy start."""
    seen = [(x, z, n) for x, z, n in (seen_clusters or [])
            if n >= 2 and dist((x, z), ctx.start) > base_radius * 1.2]
    if seen:
        if state.aggression >= 3:
            best = max(seen, key=lambda c: c[2])
        else:
            best = min(seen, key=lambda c: dist((c[0], c[1]), from_pos))
        return (best[0], best[1])
    if not ctx.enemies:
        return None
    nearest_enemy = min(ctx.enemies, key=lambda e: dist(e, from_pos))
    n_waves = len(state.waves)
    candidates = []
    for m in ctx.info.mass:
        p = (m.x, m.z)
        d_enemy = dist(p, nearest_enemy)
        d_me = dist(p, ctx.start)
        if d_enemy < d_me * 0.8 and d_enemy > 12:
            candidates.append((dist(p, from_pos), p))
    candidates.sort()
    # Rotate through expansions on successive waves; every third wave hits the base.
    if candidates and n_waves % 3 != 2 and state.aggression < 3:
        return candidates[n_waves % len(candidates)][1]
    return nearest_enemy


def should_launch(state: BotState, settings: dict) -> bool:
    if state.result:
        return False
    gap = {1: 60, 2: 35, 3: 15}.get(state.aggression, 35)
    if state.waves and time.time() - state.waves[-1].started < gap:
        return False
    return estimate_army(state) >= threshold(state, settings)


def record_wave(state: BotState, size: int, target: Tuple[float, float], reason: str) -> Wave:
    w = Wave(started=time.time(), size=size, target=target, reason=reason)
    state.waves.append(w)
    state.army_seen = None
    state.event(f"Angriffswelle {len(state.waves)}: ~{size} Einheiten -> ({int(target[0])},{int(target[1])}) [{reason}]")
    return w
