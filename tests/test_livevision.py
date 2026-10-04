import time

import numpy as np

from supcombot import config
from supcombot.camera import Camera
from supcombot.game import Game
from supcombot.livevision import FrameStream, Perception
from supcombot.planner.builder import make_context
from supcombot.state import BotState
from tests.test_maps import make_map
from tests.test_ui import FakeFiles


def make_env(tmp_path):
    info = make_map(tmp_path)
    settings = config.load_settings()
    settings["advanced"]["dry_run"] = True
    game = Game(settings, FakeFiles([]))
    game.rect = (0, 0, 1600, 900)
    game.ui.scale = 1.0
    camera = Camera(game, info)
    camera.rect = (300, 150, 1000, 500)
    ctx = make_context(info, 1, [])
    state = BotState()
    state.team_color = [0, 255, 0]
    state.enemy_colors = [[255, 0, 0]]
    stream = FrameStream(game, fps=5, backend="mss")
    perc = Perception(stream, game, camera, ctx, state, hz=5)
    return info, game, camera, ctx, stream, perc


def test_perception_reads_bars_army_and_enemies(tmp_path):
    info, game, camera, ctx, stream, perc = make_env(tmp_path)
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame[150:650, 300:1300] = 60                  # the map area (grey terrain)
    frame[17:20, 55:105] = (183, 230, 50)          # mass bar half full (first reading defines the length...)
    frame[46:49, 55:155] = (255, 179, 64)          # energy bar full
    for i in range(3):
        cx, cy = camera.world_to_client(ctx.rally[0] - 10 + i * 8, ctx.rally[1])
        frame[cy - 1:cy + 2, cx - 1:cx + 2] = (0, 255, 0)
    for i in range(2):
        cx, cy = camera.world_to_client(ctx.start[0] + 15, ctx.start[1] + 10 + i * 12)
        frame[cy - 1:cy + 2, cx - 1:cx + 2] = (255, 0, 0)
    p = perc.analyze(frame, time.time())
    assert p.ui_visible
    assert p.energy > 0.95
    assert p.map_view_valid
    assert p.army_seen == 3
    assert p.enemies_near_base == 2
    assert p.enemy_world is not None
    assert abs(p.enemy_world[0] - (ctx.start[0] + 15)) < 3


def test_perception_ignores_map_when_zoomed_in(tmp_path):
    info, game, camera, ctx, stream, perc = make_env(tmp_path)
    frame = np.full((900, 1600, 3), 90, dtype=np.uint8)   # terrain fills the screen: not the strategic view
    p = perc.analyze(frame, time.time())
    assert not p.ui_visible
    assert not p.map_view_valid
    assert p.army_seen is None and p.enemies_near_base == 0
