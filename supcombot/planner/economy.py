"""Economy evaluation (storage bars + sign of the income numbers) and the budgets derived from it."""
from __future__ import annotations

from ..state import BotState


class Economy:
    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def apply(self, mass: float, energy: float, state: BotState, mass_income: float = 0.0, energy_income: float = 0.0) -> None:
        """Feed bar ratios (0..1) and income signs (-1..1) from the live perception into the state."""
        state.mass_ratio, state.energy_ratio = mass, energy
        state.mass_income, state.energy_income = mass_income, energy_income
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
        state.mass_stall = (mh[-1] < 0.06 and falling_m) or (mh[-1] < 0.2 and state.mass_income < -0.5)
        state.energy_stall = (eh[-1] < 0.1 and falling_e) or (eh[-1] < 0.25 and state.energy_income < -0.5)
        state.energy_low = eh[-1] < 0.35 and (falling_e or state.energy_income < 0)
        state.mass_float = mh[-1] > 0.85 and not falling_m

    # Budgets derived from storage ratios only (income is not readable without OCR).
    @staticmethod
    def build_budget(state: BotState) -> int:
        t = state.game_time()
        base = 2 + int(t // 150)          # grows with time as the eco grows
        if state.mass_float:
            base += 3
        if state.mass_stall:
            base = max(1, base - 3)
        if state.strategy == "eco":
            base += 1
        return max(1, min(base, 12))

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
            return 5
        return 3

    @staticmethod
    def can_upgrade_factory(state: BotState) -> bool:
        t = state.game_time()
        min_t = {"rush": 660, "balanced": 450, "eco": 390, "turtle": 500}.get(state.strategy, 450)
        if t < min_t or state.mass_stall or state.energy_stall:
            return False
        return state.mass_ratio > 0.45 and state.energy_ratio > 0.5 and state.count_base("mex") >= 6

    @staticmethod
    def can_upgrade_factory_t3(state: BotState) -> bool:
        t = state.game_time()
        min_t = {"rush": 1500, "balanced": 1080, "eco": 900, "turtle": 1200}.get(state.strategy, 1080)
        if t < min_t or state.mass_stall or state.energy_stall:
            return False
        return state.mass_ratio > 0.6 and state.energy_ratio > 0.5 and state.count_base("mex") >= 9

    @staticmethod
    def can_upgrade_mex_t3(state: BotState) -> bool:
        if state.mass_stall or state.energy_stall or state.game_time() < 900:
            return False
        return state.mass_ratio > 0.6 and state.energy_ratio > 0.55 and state.count_base("mex") >= 8
