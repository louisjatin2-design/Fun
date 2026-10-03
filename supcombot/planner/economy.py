"""Economy reading (storage bars) and stall logic."""
from __future__ import annotations

import numpy as np

from .. import vision
from ..state import BotState


class Economy:
    def __init__(self, profile, settings: dict) -> None:
        self.profile = profile
        self.settings = settings
        self.ok = all(profile.has(k) for k in ("ui.eco.mass_left", "ui.eco.mass_right", "ui.eco.energy_left", "ui.eco.energy_right"))

    def read(self, img: np.ndarray, state: BotState) -> None:
        if not self.ok:
            return
        ml, mr = self.profile.point("ui.eco.mass_left"), self.profile.point("ui.eco.mass_right")
        el, er = self.profile.point("ui.eco.energy_left"), self.profile.point("ui.eco.energy_right")
        mass = vision.bar_fill_ratio(img, ml[0], mr[0], (ml[1] + mr[1]) // 2)
        energy = vision.bar_fill_ratio(img, el[0], er[0], (el[1] + er[1]) // 2)
        self.apply(mass, energy, state)

    def apply(self, mass: float, energy: float, state: BotState) -> None:
        """Feed bar ratios (from a screenshot or the live perception) into the state."""
        state.mass_ratio, state.energy_ratio = mass, energy
        state.mass_history = (state.mass_history + [mass])[-20:]
        state.energy_history = (state.energy_history + [energy])[-20:]
        self.evaluate(state)

    @staticmethod
    def evaluate(state: BotState) -> None:
        mh, eh = state.mass_history[-5:], state.energy_history[-5:]
        if not mh:
            return
        falling_m = len(mh) >= 3 and mh[-1] <= mh[0]
        falling_e = len(eh) >= 3 and eh[-1] <= eh[0]
        state.mass_stall = mh[-1] < 0.06 and falling_m
        state.energy_stall = eh[-1] < 0.1 and falling_e
        state.energy_low = eh[-1] < 0.3 and falling_e
        state.mass_float = mh[-1] > 0.85 and not falling_m

    # Budgets derived from storage ratios only (income is not readable without OCR).
    @staticmethod
    def build_budget(state: BotState) -> int:
        t = state.game_time()
        base = 2 + int(t // 180)          # grows with time as the eco grows
        if state.mass_float:
            base += 3
        if state.mass_stall:
            base = max(1, base - 3)
        if state.strategy == "eco":
            base += 1
        return max(1, min(base, 10))

    @staticmethod
    def can_upgrade(state: BotState) -> bool:
        if state.mass_stall or state.energy_stall:
            return False
        need = {"eco": 0.3, "balanced": 0.4, "rush": 0.6, "turtle": 0.45}.get(state.strategy, 0.4)
        return state.mass_ratio > need and state.energy_ratio > 0.4

    @staticmethod
    def factory_queue_size(state: BotState) -> int:
        if state.mass_stall:
            return 1
        if state.mass_float:
            return 4
        return 2

    @staticmethod
    def can_upgrade_factory(state: BotState) -> bool:
        t = state.game_time()
        min_t = {"rush": 720, "balanced": 480, "eco": 420, "turtle": 540}.get(state.strategy, 480)
        if t < min_t or state.mass_stall or state.energy_stall:
            return False
        return state.mass_ratio > 0.5 and state.energy_ratio > 0.5 and state.count("mex") >= 6

    @staticmethod
    def can_upgrade_factory_t3(state: BotState) -> bool:
        t = state.game_time()
        min_t = {"rush": 1500, "balanced": 1080, "eco": 900, "turtle": 1200}.get(state.strategy, 1080)
        if t < min_t or state.mass_stall or state.energy_stall:
            return False
        return state.mass_ratio > 0.6 and state.energy_ratio > 0.5 and state.count("mex") >= 9

    @staticmethod
    def can_upgrade_mex_t3(state: BotState) -> bool:
        if state.mass_stall or state.energy_stall or state.game_time() < 900:
            return False
        return state.mass_ratio > 0.6 and state.energy_ratio > 0.55 and state.count("mex") >= 8
