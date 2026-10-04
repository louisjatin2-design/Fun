"""Factory production decisions (role names, see uef.UNITS for the blueprint ids)."""
from __future__ import annotations

from typing import Dict, List

from ..state import BotState

DEFAULT_MIX: Dict[str, Dict[str, float]] = {
    "balanced": {"tank": 0.55, "arty": 0.2, "maa": 0.15, "scout": 0.1},
    "rush": {"tank": 0.65, "lab": 0.1, "arty": 0.1, "maa": 0.1, "scout": 0.05},
    "eco": {"tank": 0.5, "arty": 0.2, "maa": 0.2, "scout": 0.1},
    "turtle": {"tank": 0.4, "arty": 0.3, "maa": 0.25, "scout": 0.05},
}
LAND_ROLES = ("eng", "tank", "arty", "maa", "scout", "lab")
AIR_ROLES = ("airScout", "inter", "bomber")


def engineer_target(state: BotState, settings: dict) -> int:
    n = int(settings.get("max_engineers", 14))
    if state.advice and state.advice.get("maxEngineers"):
        n = int(state.advice["maxEngineers"])
    if state.strategy == "eco":
        n += 4
    if state.strategy == "rush":
        n = max(4, n - 4)
    cap = 4 + state.count_base("mex") * 2
    return max(3, min(n, cap, 40))


def army_mix(state: BotState) -> Dict[str, float]:
    if state.advice and state.advice.get("armyMix"):
        return state.advice["armyMix"]
    return DEFAULT_MIX.get(state.strategy, DEFAULT_MIX["balanced"])


def land_queue(state: BotState, settings: dict, available: List[str], count: int) -> List[str]:
    """Roles to queue in a land factory: engineers first until the target, then the army mix."""
    out: List[str] = []
    target = engineer_target(state, settings)
    mix = army_mix(state)
    for _ in range(count):
        if state.engineers_ordered < 3 or state.engineers_alive_estimate() < target:
            if "eng" in available:
                out.append("eng")
                state.engineers_ordered += 1
                continue
        role = pick_role(state, mix, available)
        out.append(role)
        state.army_ordered += 1
    return out


def pick_role(state: BotState, mix: Dict[str, float], available: List[str]) -> str:
    # Deterministic weighted round robin.
    slot = (state.army_ordered * 0.37) % 1.0
    acc = 0.0
    chosen = "tank"
    for role in ("tank", "arty", "maa", "scout", "lab"):
        acc += mix.get(role, 0.0)
        chosen = role
        if slot < acc:
            break
    if chosen not in available:
        chosen = "tank" if "tank" in available else (available[0] if available else "tank")
    return chosen


def air_queue(state: BotState, available: List[str], count: int) -> List[str]:
    out: List[str] = []
    for _ in range(count):
        if state.air_ordered == 0 and "airScout" in available:
            out.append("airScout")
        elif state.focus == "air" and "bomber" in available and state.air_ordered % 3 == 2:
            out.append("bomber")
        elif "inter" in available:
            out.append("inter")
        elif available:
            out.append(available[0])
        state.air_ordered += 1
    return out


def tier_roles(roles: List[str], tech: int, available: List[str]) -> List[str]:
    """Map T1 roles to the highest available variant the factory can build (T3 > T2 > T1)."""
    if tech < 2:
        return roles
    out = []
    for r in roles:
        chosen = r
        for t in range(min(tech, 3), 1, -1):
            if f"{r}{t}" in available:
                chosen = f"{r}{t}"
                break
        out.append(chosen)
    return out


def role_tier(role: str) -> int:
    return 3 if role.endswith("3") else 2 if role.endswith("2") or role in ("shield2m", "hover2", "mml2") else 1


def wants_home_guard(state: BotState) -> bool:
    return state.strategy == "turtle" or state.aggression == 1
