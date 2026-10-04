"""UI recognition tests with synthetic frames (the real game cannot run here)."""
import numpy as np

from supcombot import vision
from supcombot.gamefiles import GameFiles, parse_blueprint, parse_keymap, parse_user_keymap
from supcombot.ui import SLOT_PX, UIModel


class FakeFiles(GameFiles):
    """GameFiles replacement that serves random but fixed icons instead of reading textures.scd."""

    def __init__(self, ids, size=64, seed=1):
        super().__init__(None)
        rng = np.random.default_rng(seed)
        self.icons = {}
        for i in ids:
            icon = rng.integers(0, 255, (size, size, 4), dtype=np.uint8)
            icon[:, :, 3] = 255
            self.icons[i] = icon

    def unit_icon(self, bp_id):
        return self.icons.get(bp_id.lower())

    def keymap(self):
        return {"attack": "A", "patrol": "P"}


def make_frame(ui: UIModel, ids, scale=1.0, w=1600, h=900, groups=((0, 3), (3, 5))):
    """Paint a construction panel with the given icons at the bottom of a terrain-coloured frame."""
    frame = np.full((h, w, 3), (120, 100, 70), dtype=np.uint8)
    slot = int(SLOT_PX * scale)
    row_top = h - int(110 * scale)
    frame[h - int(150 * scale):, :] = (48, 41, 30)      # panel
    x = int(400 * scale)
    positions = {}
    for idx, bp in enumerate(ids):
        if any(idx == g[0] for g in groups[1:]):
            x += int(20 * scale)
        tpl = ui.template(bp, slot)
        frame[row_top:row_top + slot, x:x + slot] = tpl
        positions[bp] = (x + slot // 2, row_top + slot // 2)
        x += slot
    return frame, positions, row_top


def test_panel_recognition_and_scale():
    ids = ["ueb0101", "ueb0102", "ueb0103", "ueb1103", "ueb1101"]
    files = FakeFiles(ids)
    ui = UIModel(files)
    frame, positions, row_top = make_frame(ui, ids)
    panel = ui.read_panel(frame, ids + ["ueb2101"])
    assert ui.scale == 1.0
    assert set(panel.items) == set(ids)
    for bp, pos in positions.items():
        assert abs(panel.items[bp][0] - pos[0]) <= 2 and abs(panel.items[bp][1] - pos[1]) <= 2
    assert panel.row_top == row_top
    assert panel.kind() == "builder"
    assert ui.tab_position(2) is not None


def test_panel_recognition_at_dpi_150():
    ids = ["ueb0101", "ueb1103", "ueb1101", "uel0105"]
    files = FakeFiles(ids, seed=3)
    ui = UIModel(files)
    frame, positions, _ = make_frame(ui, ids, scale=1.5, w=2560, h=1400)
    panel = ui.read_panel(frame, ids)
    assert ui.scale == 1.5
    assert set(panel.items) == set(ids)
    assert panel.kind() == "land"


def test_no_panel_gives_empty_result():
    ids = ["ueb0101", "ueb1103"]
    ui = UIModel(FakeFiles(ids))
    frame = np.random.default_rng(5).integers(0, 255, (600, 900, 3), dtype=np.uint8)
    panel = ui.read_panel(frame, ids)
    assert not panel.items


def test_economy_bars_and_income_sign():
    ui = UIModel(FakeFiles([]))
    frame = np.full((300, 600, 3), (70, 58, 40), dtype=np.uint8)
    frame[17:20, 55:155] = (183, 230, 50)      # mass bar full
    frame[46:49, 55:115] = (255, 179, 64)      # energy bar 60 %
    frame[14:34, 170:200] = (60, 220, 60)      # green "+5" next to the mass bar
    frame[43:63, 170:200] = (220, 40, 40)      # red "-20" next to the energy bar
    eco = ui.read_economy(frame)
    assert eco.mass is not None and abs(eco.mass - 1.0) < 0.01
    assert eco.mass_income > 0.5
    first_energy = eco.energy
    assert first_energy is not None and abs(first_energy - 1.0) < 0.01    # first reading defines the full length
    frame[46:49, 55:155] = (255, 179, 64)
    eco = ui.read_economy(frame)
    assert abs(eco.energy - 1.0) < 0.01
    frame[46:49, 55:155] = (70, 58, 40)
    frame[46:49, 55:95] = (255, 179, 64)
    eco = ui.read_economy(frame)
    assert abs(eco.energy - 0.4) < 0.03
    assert eco.energy_income < -0.5


def test_idle_engineer_button():
    ids = ["uel0105", "ueb0101"]
    files = FakeFiles(ids, seed=7)
    ui = UIModel(files)
    ui.scale = 1.0
    frame = np.full((1000, 1600, 3), (120, 100, 70), dtype=np.uint8)
    tpl = ui.template("uel0105", 40)
    frame[300:340, 1540:1580] = tpl
    pos = ui.idle_engineer(frame)
    assert pos is not None and abs(pos[0] - 1560) <= 2 and abs(pos[1] - 320) <= 2
    assert ui.idle_factory(frame) is None


def test_blueprint_and_keymap_parsing():
    bp = parse_blueprint("ueb1103", """UnitBlueprint {
        BuildIconSortPriority = 40,
        Categories = { 'BUILTBYCOMMANDER', 'SORTECONOMY', 'TECH1', "UEF" },
        Economy = { BuildableCategory = { 'BUILTBYTIER1ENGINEER UEF' } },
        General = { UnitName = '<LOC ueb1103_name>Mass Extractor' },
        Physics = { SkirtSizeX = 2, SkirtSizeZ = 2 },
    }""")
    assert bp.sort == 40 and "SORTECONOMY" in bp.categories and bp.name == "Mass Extractor" and bp.skirt == 2
    assert bp.buildable == ["BUILTBYTIER1ENGINEER UEF"]
    km = parse_keymap("defaultKeyMap = {\n ['Ctrl-A'] = 'select_air', -- comment ['X'] = 'y'\n ['Comma'] = 'goto_commander',\n}")
    assert km == {"Ctrl-A": "select_air", "Comma": "goto_commander"}
    prefs = "profile = { UserKeyMap = { ['Home'] = 'select_commander', ['Alt-X'] = 'attack' }, other = { ['Q'] = 'zoom' } }"
    assert parse_user_keymap(prefs) == {"Home": "select_commander", "Alt-X": "attack"}


def test_menu_order_uses_vanilla_sorting(tmp_path):
    files = GameFiles(None)
    files._bp_cache = {
        "ueb0101": parse_blueprint("ueb0101", "BuildIconSortPriority = 10, Categories = {'SORTCONSTRUCTION'}"),
        "ueb1103": parse_blueprint("ueb1103", "BuildIconSortPriority = 40, Categories = {'SORTECONOMY'}"),
        "ueb1101": parse_blueprint("ueb1101", "BuildIconSortPriority = 70, Categories = {'SORTECONOMY'}"),
        "ueb2101": parse_blueprint("ueb2101", "BuildIconSortPriority = 110, Categories = {'SORTDEFENSE'}"),
        "ueb3101": parse_blueprint("ueb3101", "BuildIconSortPriority = 10, Categories = {'SORTINTEL'}"),
    }
    assert files.menu_order(["ueb3101", "ueb1101", "ueb2101", "ueb1103", "ueb0101"]) == ["ueb0101", "ueb1103", "ueb1101", "ueb2101", "ueb3101"]


def test_ncc_finds_template():
    rng = np.random.default_rng(2)
    img = rng.integers(0, 255, (120, 200, 3), dtype=np.uint8)
    tpl = img[40:64, 100:124].copy()
    score, x, y = vision.best_match(img, tpl)
    assert score > 0.99 and (x, y) == (100, 40)
    matches = vision.all_matches(img, tpl, 0.9)
    assert matches and (matches[0][1], matches[0][2]) == (100, 40)
