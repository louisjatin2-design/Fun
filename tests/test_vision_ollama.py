import numpy as np

from supcombot import vision
from supcombot.ollama import parse_advice


def test_detect_map_rect():
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[50:250, 100:300] = 120  # map area
    img[0:20, :] = 200           # top UI bar (excluded)
    rect = vision.detect_map_rect(img, exclude=[(0, 0, 400, 22)], expected_aspect=1.0)
    assert rect == (100, 50, 200, 200)


def test_bar_fill_ratio():
    img = np.zeros((10, 100, 3), dtype=np.uint8)
    img[5, 10:55] = 255
    ratio = vision.bar_fill_ratio(img, 10, 90, 5)
    assert abs(ratio - 45 / 80) < 0.02


def test_count_blobs():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:5, 2:5] = True
    mask[10:13, 10:13] = True
    mask[0, 19] = True  # too small
    assert vision.count_blobs(mask, min_pixels=3) == 2


def test_patch_similarity():
    img = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
    patch = vision.extract_patch(img, 25, 25, 10)
    assert vision.patch_similarity(img, patch, 25, 25) > 0.99
    assert vision.match_template_at(img, patch, 27, 25, search=2) > 0.99


def test_parse_advice():
    adv = parse_advice('Hier: {"strategy": "rush", "attackThreshold": 500, "armyMix": {"tank": 3, "arty": 1}, "note": "go"}')
    assert adv["strategy"] == "rush"
    assert adv["attackThreshold"] == 120
    assert abs(adv["armyMix"]["tank"] - 0.75) < 1e-6
    assert parse_advice("kein json") is None
