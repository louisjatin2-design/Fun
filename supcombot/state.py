"""Everything the bot believes about the current game (it cannot read game memory, so this is its own bookkeeping)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


@dataclass
class Structure:
    role: str
    x: float
    z: float
    ordered_at: float
    builder: str = "eng"
    marker: Optional[str] = None       # mass/hydro marker name for mex/hydro
    tech: int = 1
    upgrades: int = 0
    queued_units: int = 0              # for factories: units queued so far
    last_queue_at: float = 0.0
    rally_set: bool = False
    kind: str = "land"                 # factory kind
    repeat_set: bool = False
    home_guard: bool = False
    upgrading_until: float = 0.0

    def pos(self) -> Tuple[float, float]:
        return self.x, self.z


@dataclass
class Wave:
    started: float
    size: int
    target: Tuple[float, float]
    reason: str = "auto"
    last_pos: Optional[Tuple[float, float]] = None   # where the wave was last seen (live vision)
    seen: int = 0                                     # friendly icons near last_pos
    retreating: bool = False
    done: bool = False
    last_update: float = 0.0
    lost_since: float = 0.0


@dataclass
class BotState:
    started_at: float = field(default_factory=time.time)
    structures: List[Structure] = field(default_factory=list)
    mex_taken: Set[str] = field(default_factory=set)
    engineers_ordered: int = 0
    army_ordered: int = 0
    air_ordered: int = 0
    army_estimate: float = 0.0
    army_seen: Optional[int] = None    # blob count at the rally point (vision), if available
    waves: List[Wave] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    mass_ratio: float = 1.0
    energy_ratio: float = 1.0
    mass_history: List[float] = field(default_factory=list)
    energy_history: List[float] = field(default_factory=list)
    mass_stall: bool = False
    energy_stall: bool = False
    mass_float: bool = False
    energy_low: bool = False
    phase: str = "opening"
    strategy: str = "balanced"
    aggression: int = 2
    focus: str = "land"
    advice: Optional[dict] = None
    advice_at: float = 0.0
    opening_done: bool = False
    result: Optional[str] = None       # "won" / "lost"
    last_upgrade_at: float = 0.0
    last_idle_eng_at: float = 0.0
    last_status: str = ""
    layout_slots: int = 0
    idle_engineers_seen: int = 0
    blocked_spots: List[Tuple[float, float]] = field(default_factory=list)   # placements the game refused
    placements_rejected: int = 0
    factory_upgrades: int = 0
    acu_retreats: int = 0
    last_acu_action: float = 0.0
    strategy_auto: Optional[str] = None
    debrief: str = ""

    # ------------------------------------------------------------------ helpers
    def game_time(self) -> float:
        return time.time() - self.started_at

    def event(self, msg: str) -> None:
        stamp = f"[{int(self.game_time()) // 60:02d}:{int(self.game_time()) % 60:02d}] "
        self.events.append(stamp + msg)
        self.events = self.events[-60:]
        self.last_status = msg

    def count(self, role: str) -> int:
        return sum(1 for s in self.structures if s.role == role)

    def count_prefix(self, prefix: str) -> int:
        return sum(1 for s in self.structures if s.role.startswith(prefix))

    def factories(self, kind: Optional[str] = None) -> List[Structure]:
        out = [s for s in self.structures if s.role in ("landFac", "airFac")]
        if kind:
            out = [s for s in out if s.kind == kind]
        return out

    def add_structure(self, role: str, x: float, z: float, builder: str = "eng", marker: Optional[str] = None) -> Structure:
        s = Structure(role=role, x=x, z=z, ordered_at=time.time(), builder=builder, marker=marker,
                      kind="air" if role == "airFac" else "land")
        self.structures.append(s)
        if marker:
            self.mex_taken.add(marker)
        return s

    def engineers_alive_estimate(self) -> int:
        # Engineers die; assume 85% survive. ACU not counted.
        return int(self.engineers_ordered * 0.85)

    def snapshot(self) -> dict:
        t = self.game_time()
        return {
            "t": int(t),
            "phase": self.phase,
            "strategy": self.strategy,
            "aggression": self.aggression,
            "focus": self.focus,
            "mass": {"ratio": round(self.mass_ratio, 2), "stall": self.mass_stall, "float": self.mass_float},
            "energy": {"ratio": round(self.energy_ratio, 2), "stall": self.energy_stall, "low": self.energy_low},
            "structures": {
                "mex": self.count("mex"), "pgen": self.count("pgen") + self.count("pgen2"), "landFac": self.count("landFac"),
                "airFac": self.count("airFac"), "pd": self.count("pd") + self.count("pd2"), "aa": self.count("aa") + self.count("aa2"),
                "radar": self.count("radar"), "storage": self.count("massStorage"), "hydro": self.count("hydro"),
            },
            "units": {"engineersOrdered": self.engineers_ordered, "armyOrdered": self.army_ordered, "airOrdered": self.air_ordered,
                      "armyEstimate": int(self.army_estimate), "armySeen": self.army_seen},
            "waves": len(self.waves),
            "advice": (self.advice or {}).get("note", ""),
            "layoutSlots": self.layout_slots,
            "idleEngineersSeen": self.idle_engineers_seen,
            "placementsRejected": self.placements_rejected,
            "factoryUpgrades": self.factory_upgrades,
            "activeWaves": [{"size": w.size, "seen": w.seen, "retreating": w.retreating} for w in self.waves if not w.done],
        }
