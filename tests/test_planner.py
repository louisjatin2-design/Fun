from supcombot import layouts
from supcombot.planner import attack, production
from supcombot.planner.builder import choose_spot, make_context, opening_orders, wishlist
from supcombot.planner.economy import Economy
from supcombot.state import BotState
from tests.test_maps import make_map


def ctx_for(tmp_path):
    info = make_map(tmp_path)
    return make_context(info, 1, [])


def test_context_directions(tmp_path):
    ctx = ctx_for(tmp_path)
    assert ctx.start == (50, 60)
    assert ctx.enemies == [(450, 200)]
    assert ctx.toward[0] > 0  # enemy is to the right
    assert ctx.away[0] < 0
    assert ctx.rally[0] > ctx.start[0]


def test_opening_orders_use_markers(tmp_path):
    ctx = ctx_for(tmp_path)
    state = BotState()
    orders = opening_orders(state, ctx, None, set())
    roles = [o.role for o in orders]
    assert roles[0] == "landFac"
    assert "mex" in roles and "pgen" in roles
    mex = [o for o in orders if o.role == "mex"][0]
    assert mex.pos == (60.5, 70.5)
    assert "Mass01" in state.mex_taken
    # Structures must not overlap each other or the start marker.
    for a in state.structures:
        for b in state.structures:
            if a is not b:
                assert (a.x, a.z) != (b.x, b.z)


def test_wishlist_prioritises_energy_stall(tmp_path):
    ctx = ctx_for(tmp_path)
    state = BotState()
    state.opening_done = True
    state.energy_stall = True
    state.energy_history = [0.3, 0.2, 0.05]
    wishes = wishlist(state, ctx, {"max_engineers": 12}, has_t2_items=False)
    assert wishes[0].role == "pgen"
    assert any(w.role == "landFac" for w in wishes)


def test_choose_spot_respects_layout(tmp_path):
    ctx = ctx_for(tmp_path)
    state = BotState()
    layout = {"entries": [{"role": "pgen", "dx": -10, "dz": 0}]}
    used = set()
    from supcombot.planner.builder import Wish

    p = choose_spot(state, ctx, Wish("pgen", 50), layout, used)
    assert p == (40, 60)
    assert used == {0}
    # Second pgen falls back to the spiral and does not reuse the slot.
    state.add_structure("pgen", 40, 60)
    p2 = choose_spot(state, ctx, Wish("pgen", 50), layout, used)
    assert p2 is not None and p2 != (40, 60)


def test_economy_stall_detection():
    s = BotState()
    s.mass_history = [0.5, 0.2, 0.05]
    s.energy_history = [0.9, 0.9, 0.9]
    Economy.evaluate(s)
    assert s.mass_stall and not s.energy_stall
    assert Economy.build_budget(s) >= 1


def test_production_engineers_first():
    s = BotState()
    roles = production.land_queue(s, {"max_engineers": 12}, ["eng", "tank", "arty"], 3)
    assert roles[:3] == ["eng", "eng", "eng"]
    s.engineers_ordered = 50
    roles = production.land_queue(s, {"max_engineers": 4}, ["eng", "tank", "arty"], 4)
    assert "eng" not in roles


def test_attack_threshold_and_target(tmp_path):
    ctx = ctx_for(tmp_path)
    s = BotState()
    s.strategy = "rush"
    assert attack.threshold(s, {"attack_threshold": 20}) == 12
    target = attack.pick_target(s, ctx, ctx.rally)
    assert target is not None
    s.army_ordered = 30
    assert attack.should_launch(s, {"attack_threshold": 20})
    attack.record_wave(s, 20, target, "test")
    assert not attack.should_launch(s, {"attack_threshold": 20})  # gap not elapsed


def test_layout_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(layouts.config, "LAYOUTS_DIR", tmp_path)
    rec = layouts.store_result("map", "1_2", True, [{"role": "pgen", "dx": 1, "dz": 2}])
    assert rec["wins"] == 1
    assert layouts.load("map", "1_2")["entries"][0]["role"] == "pgen"
    layouts.store_result("map", "1_2", False, [])
    layouts.store_result("map", "1_2", False, [])
    assert layouts.load("map", "1_2") is None  # forgotten after two losses


def test_allies_are_not_enemies(tmp_path):
    info = make_map(tmp_path)
    ctx = make_context(info, 1, [], ally_slots=[2])
    assert ctx.enemies == []
    assert attack.pick_target(BotState(), ctx, ctx.rally) is None


def test_seen_clusters_are_preferred(tmp_path):
    ctx = ctx_for(tmp_path)
    s = BotState()
    clusters = [(300.0, 150.0, 5), (ctx.start[0] + 5, ctx.start[1] + 5, 9)]  # second one is inside our base
    assert attack.pick_target(s, ctx, ctx.rally, clusters, 60.0) == (300.0, 150.0)
    s.aggression = 3
    clusters.append((420.0, 180.0, 12))
    assert attack.pick_target(s, ctx, ctx.rally, clusters, 60.0) == (420.0, 180.0)
