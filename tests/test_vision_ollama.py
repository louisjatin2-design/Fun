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


def test_blob_centroids_and_clusters():
    mask = np.zeros((30, 30), dtype=bool)
    mask[2:5, 2:5] = True
    mask[3:6, 8:11] = True
    mask[20:23, 20:23] = True
    cents = vision.blob_centroids(mask, min_pixels=3)
    assert len(cents) == 3
    clusters = vision.cluster_points(cents, radius=8)
    assert len(clusters) == 2
    assert clusters[0][2] == 18  # the two close blobs merged (9 + 9 pixels)


def test_placement_verdict_and_colours():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    assert vision.placement_verdict(frame, 20, 20, 8) == "unknown"
    frame[15:25, 15:25] = (220, 30, 30)
    assert vision.placement_verdict(frame, 20, 20, 8) == "blocked"
    frame[15:25, 15:25] = (40, 220, 40)
    assert vision.placement_verdict(frame, 20, 20, 8) == "ok"
    assert vision.whiteness(np.full((5, 5, 3), 230, dtype=np.uint8)) == 25
    reg = np.full((9, 9, 3), (40, 40, 40), dtype=np.uint8)
    reg[2:7, 2:7] = (200, 30, 30)
    col = vision.dominant_color(reg)
    assert col and col[0] > 150 and col[1] < 60
