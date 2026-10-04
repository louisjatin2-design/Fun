"""Bot logic in dry-run mode with a fake game (no window, no input)."""
import time

import numpy as np

from supcombot import config, uef
from supcombot.bot import Bot
from supcombot.game import Game
from supcombot.ui import Panel
from tests.test_maps import make_map
from tests.test_ui import FakeFiles


class FakeGame(Game):
    """Dry-run game whose build panel always shows what the given builder can build."""

    def __init__(self, settings, files):
        super().__init__(settings, files)
        self.rect = (0, 0, 1600, 900)
        self.ui.scale = 1.0
        self.ui.row_top = 790
        self.ui.first_left = 400
        self.menu = list(uef.T1_ENGINEER_BUILDS)
        self.clicked = []

    def screenshot(self, max_age=0.0):
        return np.full((900, 1600, 3), 70, dtype=np.uint8)

    def fresh_frame(self, settle=0.25):
        return self.screenshot()

    def panel(self, candidates=None, frame=None, settle=0.3):
        p = Panel(ts=time.time(), slot=48, row_top=790, first_left=400)
        for i, bp in enumerate(self.menu):
            if candidates is None or bp in candidates:
                p.items[bp] = (424 + i * 48, 814)
        return p

    def click_item(self, bp_id, panel=None, shift=False):
        self.clicked.append(bp_id)
        return bp_id in self.menu

    def select_tab(self, tier):
        return True

    def select_commander(self):
        return True


def make_bot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAYOUTS_DIR", tmp_path / "layouts")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DEBUG_DIR", tmp_path / "debug")
    info = make_map(tmp_path)
    settings = config.load_settings()
    settings["advanced"]["dry_run"] = True
    game = FakeGame(settings, FakeFiles([]))
    bot = Bot(settings, game, info, None)
    return bot, game


def test_opening_places_factory_and_mex(tmp_path, monkeypatch):
    bot, game = make_bot(tmp_path, monkeypatch)
    bot.state.start_detected = True
    bot.camera.rect = (100, 50, 512, 256)
    bot.do_opening()
    s = bot.state
    assert s.opening_done
    assert "ueb0101" in game.clicked and "ueb1103" in game.clicked
    assert s.count("landFac") == 1 and s.count("mex") >= 1


def test_engineer_jobs_use_wishlist(tmp_path, monkeypatch):
    bot, game = make_bot(tmp_path, monkeypatch)
    bot.state.start_detected = True
    bot.state.opening_done = True
    bot.camera.rect = (100, 50, 512, 256)
    bot.state.energy_stall = True
    bot.state.energy_history = [0.3, 0.2, 0.05]
    panel = game.panel()
    assert bot.assign_jobs(panel)
    assert "ueb1101" in game.clicked           # power generator first on an energy stall
    assert bot.state.count("pgen") >= 1


def test_factory_queue_orders_engineers_first(tmp_path, monkeypatch):
    bot, game = make_bot(tmp_path, monkeypatch)
    bot.state.start_detected = True
    bot.camera.rect = (100, 50, 512, 256)
    fac = bot.state.add_structure("landFac", 40, 40)
    game.menu = list(uef.LAND_FACTORY_T1)
    bot.queue_units("land", fac, game.panel())
    assert game.clicked[:3] == ["uel0105", "uel0105", "uel0105"]
    assert fac.rally_set and fac.queued_units == 3


def test_t2_factory_queue_prefers_t2_units(tmp_path, monkeypatch):
    bot, game = make_bot(tmp_path, monkeypatch)
    bot.state.start_detected = True
    bot.camera.rect = (100, 50, 512, 256)
    bot.state.engineers_ordered = 40
    bot.state.mass_float = True
    fac = bot.state.add_structure("landFac", 40, 40)
    fac.tech = 2
    game.menu = list(uef.LAND_FACTORY_T2)
    bot.queue_units("land", fac, game.panel())
    assert "uel0202" in game.clicked            # Pillar instead of Striker
    assert fac.tech == 2


def test_setup_game_dry_run(tmp_path, monkeypatch):
    bot, game = make_bot(tmp_path, monkeypatch)
    assert bot.setup_game()
    assert bot.state.start_detected and bot.state.team_color
