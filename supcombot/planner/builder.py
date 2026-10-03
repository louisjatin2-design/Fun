"""Build planning: what to build next and where, using map markers and the bot's own bookkeeping."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..maps import MapInfo, Marker
from ..state import BotState

# Approximate footprint (skirt) sizes in world units, used to keep structures apart.
FOOTPRINT: Dict[str, float] = {
    "landFac": 10.0, "airFac": 10.0, "pgen": 4.0, "pgen2": 7.0, "mex": 3.0, "hydro": 6.0, "massStorage": 3.0,
    "pd": 3.0, "pd2": 4.0, "aa": 3.0, "aa2": 4.0, "radar": 3.0, "shield2": 5.0, "wall": 1.0,
}


@dataclass
class Wish:
    role: str
    prio: float
    pos: Optional[Tuple[float, float]] = None
    marker: Optional[str] = None
    count: int = 1
    toward_enemy: bool = False
    near_mex: bool = False


@dataclass
class MapContext:
    info: MapInfo
    start: Tuple[float, float]
    enemies: List[Tuple[float, float]]
    away: Tuple[float, float]
    toward: Tuple[float, float]
    rally: Tuple[float, float]
    nearest_enemy: Optional[Tuple[float, float]]
    enemy_distance: float


def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def make_context(info: MapInfo, start_slot: int, enemy_slots: List[int]) -> MapContext:
    if start_slot not in info.starts:
        raise ValueError(f"Startposition {start_slot} existiert auf {info.name} nicht (vorhanden: {sorted(info.starts)})")
    s = info.starts[start_slot]
    start = (s.x, s.z)
    enemies: List[Tuple[float, float]] = []
    for n, m in info.start_positions():
        if n == start_slot:
            continue
        if enemy_slots and n not in enemy_slots:
            continue
        enemies.append((m.x, m.z))
    nearest = min(enemies, key=lambda e: dist(e, start)) if enemies else None
    if nearest:
        dx, dz = start[0] - nearest[0], start[1] - nearest[1]
        length = max(1.0, math.hypot(dx, dz))
        away = (dx / length, dz / length)
    else:
        away = (0.0, -1.0)
    toward = (-away[0], -away[1])
    d = dist(nearest, start) if nearest else 200.0
    rally_d = max(30.0, d * 0.18)
    rally = (start[0] + toward[0] * rally_d, start[1] + toward[1] * rally_d)
    rally = clamp_to_map(info, rally)
    return MapContext(info=info, start=start, enemies=enemies, away=away, toward=toward, rally=rally,
                      nearest_enemy=nearest, enemy_distance=d)


def clamp_to_map(info: MapInfo, p: Tuple[float, float], margin: float = 6.0) -> Tuple[float, float]:
    return (min(max(margin, p[0]), info.size[0] - margin), min(max(margin, p[1]), info.size[1] - margin))


# ------------------------------------------------------------------------------------------ placement
def blocked(state: BotState, ctx: MapContext, role: str, pos: Tuple[float, float], avoid_mass: bool = True) -> bool:
    size = FOOTPRINT.get(role, 3.0)
    for s in state.structures:
        need = (size + FOOTPRINT.get(s.role, 3.0)) / 2 + 1.0
        if dist(s.pos(), pos) < need:
            return True
    if avoid_mass:
        for m in ctx.info.mass:
            if dist((m.x, m.z), pos) < size / 2 + 2.5:
                return True
    # Keep the start marker free (the ACU stands there at first).
    if dist(ctx.start, pos) < size / 2 + 3.0:
        return True
    return False


def find_spot(state: BotState, ctx: MapContext, role: str, center: Tuple[float, float],
              min_r: float = 6.0, max_r: float = 80.0, avoid_mass: bool = True) -> Optional[Tuple[float, float]]:
    """Spiral search on a grid aligned to the structure size."""
    size = FOOTPRINT.get(role, 3.0)
    step = size + 1.5
    r = max(min_r, step)
    while r <= max_r:
        n = max(8, int(2 * math.pi * r / step))
        for i in range(n):
            ang = 2 * math.pi * i / n
            p = (round(center[0] + math.cos(ang) * r), round(center[1] + math.sin(ang) * r))
            if not (4 <= p[0] <= ctx.info.size[0] - 4 and 4 <= p[1] <= ctx.info.size[1] - 4):
                continue
            if not blocked(state, ctx, role, p, avoid_mass):
                return p
        r += step
    return None


def layout_spot(state: BotState, ctx: MapContext, layout: Optional[dict], used: set, role: str) -> Optional[Tuple[float, float]]:
    if not layout:
        return None
    best, best_i, best_d = None, -1, 1e12
    for i, e in enumerate(layout.get("entries", [])):
        if i in used or e.get("role") != role:
            continue
        p = (ctx.start[0] + float(e["dx"]), ctx.start[1] + float(e["dz"]))
        d = e["dx"] ** 2 + e["dz"] ** 2
        if d < best_d and not blocked(state, ctx, role, p):
            best, best_i, best_d = p, i, d
    if best is not None:
        used.add(best_i)
    return best


def choose_spot(state: BotState, ctx: MapContext, wish: Wish, layout: Optional[dict], layout_used: set,
                base_radius: float = 60.0) -> Optional[Tuple[float, float]]:
    if wish.pos:
        return wish.pos
    p = layout_spot(state, ctx, layout, layout_used, wish.role)
    if p:
        return p
    if wish.toward_enemy:
        d = base_radius * 0.6
        center = (ctx.start[0] + ctx.toward[0] * d, ctx.start[1] + ctx.toward[1] * d)
        return find_spot(state, ctx, wish.role, center, 2.0, 30.0)
    if wish.near_mex:
        mexes = [s for s in state.structures if s.role == "mex" and dist(s.pos(), ctx.start) < base_radius]
        for m in mexes:
            p = find_spot(state, ctx, wish.role, m.pos(), 2.0, 5.0, avoid_mass=False)
            if p:
                return p
        return None
    offset = 14.0 if wish.role in ("landFac", "airFac") else 8.0
    center = (ctx.start[0] + ctx.away[0] * offset, ctx.start[1] + ctx.away[1] * offset)
    min_r = 8.0 if wish.role in ("landFac", "airFac") else 5.0
    return find_spot(state, ctx, wish.role, center, min_r, base_radius + 25)


# ------------------------------------------------------------------------------------------ wishlist
def free_mass_markers(state: BotState, ctx: MapContext, max_dist: float) -> List[Marker]:
    out = []
    for m in ctx.info.mass:
        if m.name in state.mex_taken:
            continue
        d = dist((m.x, m.z), ctx.start)
        if d <= max_dist:
            out.append((d, m))
    out.sort(key=lambda t: t[0])
    return [m for _d, m in out]


def enemy_distance(ctx: MapContext, p: Tuple[float, float]) -> float:
    return min((dist(p, e) for e in ctx.enemies), default=1e9)


def wishlist(state: BotState, ctx: MapContext, settings: dict, has_t2_items: bool) -> List[Wish]:
    t = state.game_time()
    strat = state.strategy
    wishes: List[Wish] = []

    def add(role: str, prio: float, **kw) -> None:
        wishes.append(Wish(role=role, prio=prio, **kw))

    n_pgen = state.count("pgen") + state.count("pgen2") * 3
    n_mex = state.count("mex")
    n_land = state.count("landFac")
    n_air = state.count("airFac")

    # Energy: ratio of generators to consumers, plus the bar reading.
    want_pgen = 2 + n_mex // 2 + n_land * 2 + n_air * 3 + state.count("radar") * 2
    if state.energy_stall:
        add("pgen2" if has_t2_items and t > 600 else "pgen", 100, count=2)
    elif state.energy_low or n_pgen < want_pgen:
        add("pgen2" if has_t2_items and t > 600 and state.mass_ratio > 0.4 else "pgen", 82, count=2)

    if n_land == 0:
        add("landFac", 98)

    # Mass extractors within a radius that grows with time.
    radius = 45 + t / 60 * 12
    if strat == "eco":
        radius *= 1.4
    if strat == "turtle":
        radius *= 0.7
    radius = max(45.0, min(radius, max(ctx.info.size)))
    parallel = 2 + int(t // 240)
    if state.mass_float:
        parallel += 2
    if state.mass_stall:
        parallel += 1  # a stall is fixed by more mex, not fewer
    for i, m in enumerate(free_mass_markers(state, ctx, radius)):
        if i >= parallel:
            break
        d = dist((m.x, m.z), ctx.start)
        prio = 92 - min(30.0, d / 10)
        if enemy_distance(ctx, (m.x, m.z)) < d * 1.15:
            prio -= 8
        add("mex", prio, pos=(m.x, m.z), marker=m.name)

    # Hydro close to home.
    for h in ctx.info.hydro:
        if h.name not in state.mex_taken and dist((h.x, h.z), ctx.start) < 45:
            add("hydro", 86, pos=(h.x, h.z), marker=h.name)
            break

    # More factories as the game goes on (no income reading: use time, storage and mex count).
    divisor = {"rush": 2.5, "balanced": 3.5, "eco": 5.0, "turtle": 4.5}.get(strat, 3.5)
    target_land = max(1, min(6, int(n_mex / divisor) + (1 if state.mass_float else 0)))
    if state.focus == "air":
        target_land = max(1, target_land - 1)
    if n_land < target_land and not state.mass_stall:
        add("landFac", 70)
    target_air = 0
    if t > 300:
        target_air = min(3, n_mex // 6)
    if state.focus == "air":
        target_air += 1
    if n_air < target_air and not state.mass_stall:
        add("airFac", 62)

    if state.count("radar") == 0 and t > 180:
        add("radar", 66)

    want_pd = 4 if strat == "turtle" else (1 if t > 420 else 0)
    want_aa = 3 if strat == "turtle" else (2 if t > 480 else 0)
    if state.count("pd") + state.count("pd2") < want_pd:
        add("pd2" if has_t2_items else "pd", 60, toward_enemy=True)
    if state.count("aa") + state.count("aa2") < want_aa:
        add("aa2" if has_t2_items else "aa", 58, toward_enemy=(strat != "turtle"))
    if has_t2_items and t > 900 and state.count("shield2") < 1 and state.mass_ratio > 0.5:
        add("shield2", 40)
    if t > 600 and state.mass_ratio > 0.5 and state.count("massStorage") < 4:
        add("massStorage", 35, near_mex=True)

    wishes.sort(key=lambda w: w.prio, reverse=True)
    return wishes


def opening_orders(state: BotState, ctx: MapContext, layout: Optional[dict], layout_used: set) -> List[Wish]:
    """ACU opening: factory, two mex, two pgen, two more mex."""
    orders: List[Wish] = []
    fac = Wish("landFac", 100)
    fac.pos = choose_spot(state, ctx, fac, layout, layout_used)
    if fac.pos:
        orders.append(fac)
        state.add_structure("landFac", fac.pos[0], fac.pos[1], builder="acu")
    mexes = free_mass_markers(state, ctx, 60)
    for m in mexes[:2]:
        orders.append(Wish("mex", 95, pos=(m.x, m.z), marker=m.name))
        state.add_structure("mex", m.x, m.z, builder="acu", marker=m.name)
    for _ in range(2):
        w = Wish("pgen", 90)
        w.pos = choose_spot(state, ctx, w, layout, layout_used)
        if w.pos:
            orders.append(w)
            state.add_structure("pgen", w.pos[0], w.pos[1], builder="acu")
    for m in mexes[2:4]:
        orders.append(Wish("mex", 85, pos=(m.x, m.z), marker=m.name))
        state.add_structure("mex", m.x, m.z, builder="acu", marker=m.name)
    return orders
