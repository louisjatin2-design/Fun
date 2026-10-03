import time

import numpy as np

from supcombot import layouts, vision
from supcombot.planner import attack, production
from supcombot.planner.builder import DEFAULT_OPENINGS, make_context, opening_orders
from supcombot.planner.economy import Economy
from supcombot.state import BotState
from tests.test_maps import make_map


def test_placement_verdict():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    assert vision.placement_verdict(frame, 20, 20, 8) == "unknown"
    frame[15:25, 15:25] = (220, 30, 30)
    assert vision.placement_verdict(frame, 20, 20, 8) == "blocked"
    frame[15:25, 15:25] = (40, 220, 40)
    assert vision.placement_verdict(frame, 20, 20, 8) == "ok"


def test_opening_follows_sequence(tmp_path):
    info = make_map(tmp_path)
    ctx = make_context(info, 1, [])
    state = BotState()
    state.strategy = "eco"
    orders = opening_orders(state, ctx, None, set(), ["mex", "landFac", "pgen"])
    assert [o.role for o in orders] == ["mex", "landFac", "pgen"]
    assert orders[0].pos == (60.5, 70.5)
    assert "eco" in DEFAULT_OPENINGS


def test_blocked_spots_are_avoided(tmp_path):
    from supcombot.planner.builder import Wish, choose_spot

    info = make_map(tmp_path)
    ctx = make_context(info, 1, [])
    state = BotState()
    first = choose_spot(state, ctx, Wish("pgen", 50), None, set())
    state.blocked_spots.append(first)
    second = choose_spot(state, ctx, Wish("pgen", 50), None, set())
    assert second != first


def test_manage_waves_retreats_and_advances(tmp_path):
    info = make_map(tmp_path)
    ctx = make_context(info, 1, [])
    s = BotState()
    now = time.time()
    w = attack.record_wave(s, 10, (440.0, 190.0), "test", ctx.rally)
    w.started = now - 20
    # Wave seen near the rally, outnumbered 3:1 -> retreat.
    friendly = [(ctx.rally[0] + 5, ctx.rally[1], 8)]
    enemy = [(ctx.rally[0] + 15, ctx.rally[1], 30)]
    actions = attack.manage_waves(s, ctx, friendly, enemy, now)
    assert actions and actions[0][0] == "retreat"
    assert w.retreating
    # A second wave that reached its target with nobody around moves on.
    w2 = attack.record_wave(s, 10, (300.0, 150.0), "test", ctx.rally)
    w2.started = now - 20
    w2.last_pos = (290.0, 150.0)   # tracked on its way earlier
    friendly = [(298.0, 150.0, 9)]
    actions = attack.manage_waves(s, ctx, friendly, [], now)
    kinds = [a[0] for a in actions]
    assert "advance" in kinds
    assert w2.target != (300.0, 150.0)


def test_wave_lost_is_closed(tmp_path):
    info = make_map(tmp_path)
    ctx = make_context(info, 1, [])
    s = BotState()
    now = time.time()
    w = attack.record_wave(s, 6, (440.0, 190.0), "test", ctx.rally)
    w.started = now - 60
    attack.manage_waves(s, ctx, [], [], now)
    assert w.lost_since and not w.done
    attack.manage_waves(s, ctx, [], [], now + 40)
    assert w.done


def test_tier_roles_and_home_guard():
    assert production.tier_roles(["eng", "tank", "arty"], 2, ["eng2", "tank2"]) == ["eng2", "tank2", "arty"]
    assert production.tier_roles(["eng", "tank"], 1, ["eng2"]) == ["eng", "tank"]
    s = BotState()
    s.strategy = "turtle"
    assert production.wants_home_guard(s)
    s.strategy = "rush"
    s.aggression = 3
    assert not production.wants_home_guard(s)


def test_factory_upgrade_gate():
    s = BotState()
    s.started_at -= 600
    s.mass_ratio, s.energy_ratio = 0.7, 0.7
    for i in range(6):
        s.add_structure("mex", i * 10, 0)
    assert Economy.can_upgrade_factory(s)
    s.mass_stall = True
    assert not Economy.can_upgrade_factory(s)


def test_best_strategy_from_history(tmp_path, monkeypatch):
    monkeypatch.setattr(layouts.config, "LAYOUTS_DIR", tmp_path)
    assert layouts.best_strategy("m", "1_1") == "balanced"
    layouts.store_result("m", "1_1", True, [], {"strategy": "rush"})
    layouts.store_result("m", "1_1", True, [], {"strategy": "rush"})
    layouts.store_result("m", "1_1", False, [], {"strategy": "eco"})
    assert layouts.best_strategy("m", "1_1") == "rush"
