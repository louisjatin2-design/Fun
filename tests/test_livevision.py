import time

import numpy as np

from supcombot.camera import Camera
from supcombot.game import Game
from supcombot.livevision import FrameStream, Perception
from supcombot.planner.builder import make_context
from supcombot.profile import Profile
from supcombot import config
from tests.test_maps import make_map


def make_env(tmp_path):
    info = make_map(tmp_path)
    settings = config.load_settings()
    settings["dry_run"] = True
    prof = Profile("uef", (800, 400))
    for k, (x, y) in {"ui.eco.mass_left": (10, 5), "ui.eco.mass_right": (110, 5),
                      "ui.eco.energy_left": (10, 12), "ui.eco.energy_right": (110, 12)}.items():
        prof.set_point(k, x, y)
    prof.set_point("ui.exclude.top", 0, 20)   # the bars live in the top UI strip
    prof.team_color = [0, 255, 0]
    prof.enemy_colors = [[255, 0, 0]]
    prof.map_rects[info.key] = [100, 50, 512, 256]
    game = Game(settings, prof)
    camera = Camera(game, info)
    ctx = make_context(info, 1, [])
    stream = FrameStream(game, fps=5, backend="mss")
    perc = Perception(stream, game, camera, ctx, hz=5)
    return info, game, camera, ctx, stream, perc


def test_perception_reads_bars_army_and_enemies(tmp_path):
    info, game, camera, ctx, stream, perc = make_env(tmp_path)
    frame = np.zeros((400, 800, 3), dtype=np.uint8)
    frame[50:306, 100:612] = 60                    # the map area (grey terrain)
    frame[3:8, 10:60] = 255                        # mass bar half full
    frame[10:15, 10:110] = 255                     # energy bar full
    # Three friendly blobs at the rally point, two enemy blobs near the start.
    for i in range(3):
        cx, cy = camera.world_to_client(ctx.rally[0] - 10 + i * 8, ctx.rally[1])
        frame[cy - 1:cy + 2, cx - 1:cx + 2] = (0, 255, 0)
    for i in range(2):
        cx, cy = camera.world_to_client(ctx.start[0] + 15, ctx.start[1] + 10 + i * 12)
        frame[cy - 1:cy + 2, cx - 1:cx + 2] = (255, 0, 0)
    p = perc.analyze(frame, time.time())
    assert abs(p.mass - 0.5) < 0.05
    assert p.energy > 0.95
    assert p.map_view_valid
    assert p.army_seen == 3
    assert p.enemies_near_base == 2
    assert p.enemy_world is not None
    assert abs(p.enemy_world[0] - (ctx.start[0] + 15)) < 3


def test_perception_ignores_map_when_zoomed_in(tmp_path):
    info, game, camera, ctx, stream, perc = make_env(tmp_path)
    frame = np.full((400, 800, 3), 90, dtype=np.uint8)   # terrain fills the screen: not the strategic view
    p = perc.analyze(frame, time.time())
    assert not p.map_view_valid
    assert p.army_seen is None and p.enemies_near_base == 0
