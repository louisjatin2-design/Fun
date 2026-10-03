from pathlib import Path

from supcombot import maps

SCENARIO = """
version = 3
ScenarioInfo = {
    name = 'Test Map',
    description = 'x',
    type = 'skirmish',
    map = '/maps/testmap/testmap.scmap',
    save = '/maps/testmap/testmap_save.lua',
    size = {512, 256},
}
"""

SAVE = """
Scenario = {
    MasterChain = {
        ['_MASTERCHAIN_'] = {
            Markers = {
                ['ARMY_1'] = { ['type'] = STRING( 'Blank Marker' ), ['position'] = VECTOR3( 50, 10, 60 ), ['orientation'] = VECTOR3( 0, 0, 0 ) },
                ['ARMY_2'] = { ['type'] = STRING( 'Blank Marker' ), ['position'] = VECTOR3( 450, 10, 200 ) },
                ['Mass01'] = { ['type'] = STRING( 'Mass' ), ['position'] = VECTOR3( 60.5, 10, 70.5 ), ['prop'] = STRING( '/env/common/props/massDeposit01_prop.bp' ) },
                ['Mass02'] = { ['type'] = STRING( 'Mass' ), ['position'] = VECTOR3( 440, 10, 190 ) },
                ['Hydro01'] = { ['type'] = STRING( 'Hydrocarbon' ), ['position'] = VECTOR3( 80, 10, 80 ) },
            },
        },
    },
}
"""


def make_map(tmp_path: Path) -> maps.MapInfo:
    folder = tmp_path / "testmap"
    folder.mkdir()
    (folder / "testmap_scenario.lua").write_text(SCENARIO, encoding="utf-8")
    (folder / "testmap_save.lua").write_text(SAVE, encoding="utf-8")
    info = maps.load_map(folder)
    assert info is not None
    return info


def test_parse_map(tmp_path):
    info = make_map(tmp_path)
    assert info.name == "Test Map"
    assert info.size == (512, 256)
    assert sorted(info.starts) == [1, 2]
    assert info.starts[1].x == 50 and info.starts[1].z == 60
    assert [m.name for m in info.mass] == ["Mass01", "Mass02"]
    assert info.mass[0].x == 60.5
    assert len(info.hydro) == 1
    assert abs(info.aspect - 2.0) < 1e-6


def test_find_map(tmp_path):
    info = make_map(tmp_path)
    assert maps.find_map([info], "test map") is info
    assert maps.find_map([info], "TESTMAP") is info
    assert maps.find_map([info], "nope") is None
