from supcombot import layouts
from supcombot.planner import attack, production
from supcombot.planner.builder import DEFAULT_OPENINGS, Wish, choose_spot, make_context, opening_orders, wishlist
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
    for a in state.structures:
        for b in state.structures:
            if a is not b:
                assert (a.x, a.z) != (b.x, b.z)
    assert "eco" in DEFAULT_OPENINGS


def test_wishlist_prioritises_energy_stall_and_hydro(tmp_path):
    ctx = ctx_for(tmp_path)
    state = BotState()
    state.opening_done = True
    state.energy_stall = True
    state.energy_history = [0.3, 0.2, 0.05]
    wishes = wishlist(state, ctx, {"max_engineers": 12}, has_t2_items=False)
    assert wishes[0].role == "pgen"
    assert any(w.role == "landFac" for w in wishes)
    assert any(w.role == "hydro" and w.marker == "Hydro01" for w in wishes)


def test_wishlist_t2_and_t3_roles(tmp_path):
    ctx = ctx_for(tmp_path)
    s = BotState()
    s.started_at -= 1500
    s.mass_ratio = 0.7
    s.energy_stall = True
    s.energy_history = [0.5, 0.3, 0.05]
    roles = [w.role for w in wishlist(s, ctx, {}, has_t2_items=True, has_t3_items=True)]
    assert roles[0] == "pgen3"
    assert "pd3" not in roles          # UEF has no T3 point defence
    s.energy_stall = False
    s.energy_low = True
    roles = [w.role for w in wishlist(s, ctx, {}, has_t2_items=True, has_t3_items=False)]
    assert "pgen2" in roles


def test_choose_spot_respects_layout_and_blocked(tmp_path):
    ctx = ctx_for(tmp_path)
    state = BotState()
    layout = {"entries": [{"role": "pgen", "dx": -10, "dz": 0}]}
    used = set()
    p = choose_spot(state, ctx, Wish("pgen", 50), layout, used)
    assert p == (40, 60)
    assert used == {0}
    state.add_structure("pgen", 40, 60)
    p2 = choose_spot(state, ctx, Wish("pgen", 50), layout, used)
    assert p2 is not None and p2 != (40, 60)
    state.blocked_spots.append(p2)
    p3 = choose_spot(state, ctx, Wish("pgen", 50), layout, used)
    assert p3 != p2


def test_economy_stall_detection():
    s = BotState()
    s.mass_history = [0.5, 0.2, 0.05]
    s.energy_history = [0.9, 0.9, 0.9]
    Economy.evaluate(s)
    assert s.mass_stall and not s.energy_stall
    assert Economy.build_budget(s) >= 1
    s = BotState()
    s.mass_history = [0.15]
    s.energy_history = [0.9]
    s.mass_income = -0.9
    Economy.evaluate(s)
    assert s.mass_stall


def test_production_engineers_first():
    s = BotState()
    roles = production.land_queue(s, {"max_engineers": 12}, ["eng", "tank", "arty"], 3)
    assert roles[:3] == ["eng", "eng", "eng"]
    s.engineers_ordered = 50
    roles = production.land_queue(s, {"max_engineers": 4}, ["eng", "tank", "arty"], 4)
    assert "eng" not in roles
    assert production.tier_roles(["eng", "tank", "arty"], 2, ["eng2", "tank2"]) == ["eng2", "tank2", "arty"]
    assert production.air_queue(BotState(), ["airScout", "inter"], 2) == ["airScout", "inter"]


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
    layouts.store_result("m", "1_1", True, [], {"strategy": "rush"})
    layouts.store_result("m", "1_1", False, [], {"strategy": "eco"})
    assert layouts.best_strategy("m", "1_1") == "rush"


def test_allies_and_seen_clusters(tmp_path):
    info = make_map(tmp_path)
    ctx = make_context(info, 1, [], ally_slots=[2])
    assert ctx.enemies == []
    assert attack.pick_target(BotState(), ctx, ctx.rally) is None
    (tmp_path / "b").mkdir()
    ctx = ctx_for(tmp_path / "b")
    s = BotState()
    clusters = [(300.0, 150.0, 5), (ctx.start[0] + 5, ctx.start[1] + 5, 9)]  # second one is inside our base
    assert attack.pick_target(s, ctx, ctx.rally, clusters, 60.0) == (300.0, 150.0)


def test_manage_waves(tmp_path):
    import time

    info = make_map(tmp_path)
    ctx = make_context(info, 1, [])
    s = BotState()
    now = time.time()
    w = attack.record_wave(s, 10, (440.0, 190.0), "test", ctx.rally)
    w.started = now - 20
    friendly = [(ctx.rally[0] + 5, ctx.rally[1], 8)]
    enemy = [(ctx.rally[0] + 15, ctx.rally[1], 30)]
    actions = attack.manage_waves(s, ctx, friendly, enemy, now)
    assert actions and actions[0][0] == "retreat" and w.retreating
    w2 = attack.record_wave(s, 6, (440.0, 190.0), "test", ctx.rally)
    w2.started = now - 60
    attack.manage_waves(s, ctx, [], [], now)
    attack.manage_waves(s, ctx, [], [], now + 40)
    assert w2.done


def test_factory_upgrade_gates():
    s = BotState()
    s.started_at -= 600
    s.mass_ratio, s.energy_ratio = 0.7, 0.7
    for i in range(6):
        s.add_structure("mex", i * 10, 0)
    assert Economy.can_upgrade_factory(s)
    s.mass_stall = True
    assert not Economy.can_upgrade_factory(s)


def test_old_settings_are_migrated():
    from supcombot import config

    old = {"map": "auto", "start_slot": 1, "faction": "auto", "auto_attack": False, "game_dir": "D:/FA", "overlay": {"x": 5, "y": 6, "minimap": True}}
    new = config.migrate(old)
    assert new == {"game_dir": "D:/FA", "overlay": {"x": 5, "y": 6}, "settings_version": config.SETTINGS_VERSION}
    assert config.migrate(new) is new
