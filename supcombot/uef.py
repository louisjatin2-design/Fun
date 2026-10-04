"""UEF unit knowledge: blueprint ids per role, tech tiers, footprints and strategic icons.

Everything the bot clicks is identified by its blueprint id (e.g. ``ueb1103`` = T1 mass extractor). The build
menu is read from the screen by matching the game's own icon textures (``/textures/ui/common/icons/units/<id>_icon.dds``
inside ``gamedata/textures.scd`` of the Steam install), so no manual calibration is needed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

FACTION = "uef"

# role -> blueprint id (structures)
STRUCTURES: Dict[str, str] = {
    "landFac": "ueb0101", "airFac": "ueb0102", "navalFac": "ueb0103",
    "mex": "ueb1103", "pgen": "ueb1101", "hydro": "ueb1102", "massStorage": "ueb1106", "energyStorage": "ueb1105",
    "pd": "ueb2101", "aa": "ueb2104", "wall": "ueb5101", "radar": "ueb3101", "sonar": "ueb3102", "torpedo": "ueb2109",
    "airStaging": "ueb5202",
    # tech 2
    "landFac2": "ueb0201", "airFac2": "ueb0202", "mex2": "ueb1202", "pgen2": "ueb1201", "pd2": "ueb2301", "aa2": "ueb2204",
    "shield2": "ueb4202", "tml": "ueb2108", "arty2": "ueb2303", "radar2": "ueb3201", "tmd": "ueb4201",
    # tech 3
    "landFac3": "ueb0301", "airFac3": "ueb0302", "mex3": "ueb1302", "pgen3": "ueb1301", "aa3": "ueb2304", "shield3": "ueb4301",
    "arty3": "ueb2302", "omni": "ueb3104",
}

# role -> blueprint id (mobile units)
UNITS: Dict[str, str] = {
    "eng": "uel0105", "scout": "uel0101", "lab": "uel0106", "tank": "uel0201", "arty": "uel0103", "maa": "uel0104",
    "eng2": "uel0208", "tank2": "uel0202", "hover2": "uel0203", "maa2": "uel0205", "mml2": "uel0111", "shield2m": "uel0307",
    "eng3": "uel0309", "tank3": "uel0303", "arty3m": "uel0304",
    "airScout": "uea0101", "inter": "uea0102", "bomber": "uea0103", "transport": "uea0107",
    "gunship2": "uea0203", "torpBomber2": "uea0204", "asf3": "uea0303", "stratBomber3": "uea0304",
}

ALL_IDS: Dict[str, str] = {**STRUCTURES, **UNITS}
ROLE_OF_ID: Dict[str, str] = {v: k for k, v in ALL_IDS.items()}
ACU = "uel0001"

# Which blueprints a builder can produce (vanilla categories, used as a fallback when units.scd is unreadable).
ACU_BUILDS: List[str] = ["ueb0101", "ueb0102", "ueb0103", "ueb1103", "ueb1101", "ueb2101", "ueb2104", "ueb2109", "ueb5101"]
T1_ENGINEER_BUILDS: List[str] = ["ueb0101", "ueb0102", "ueb0103", "ueb1103", "ueb1106", "ueb1101", "ueb1102", "ueb1105",
                                 "ueb2101", "ueb2104", "ueb2109", "ueb5101", "ueb3101", "ueb3102", "ueb5202"]
T2_ENGINEER_BUILDS: List[str] = T1_ENGINEER_BUILDS + ["ueb0201", "ueb0202", "ueb1202", "ueb1201", "ueb2301", "ueb2204",
                                                       "ueb4201", "ueb4202", "ueb2303", "ueb2108", "ueb3201"]
T3_ENGINEER_BUILDS: List[str] = T2_ENGINEER_BUILDS + ["ueb0301", "ueb0302", "ueb1302", "ueb1301", "ueb2304", "ueb4301",
                                                       "ueb2302", "ueb3104"]
LAND_FACTORY_T1: List[str] = ["uel0105", "uel0101", "uel0106", "uel0201", "uel0104", "uel0103", "ueb0201"]
LAND_FACTORY_T2: List[str] = ["uel0105", "uel0101", "uel0106", "uel0201", "uel0104", "uel0103",
                              "uel0208", "uel0202", "uel0203", "uel0205", "uel0111", "uel0307", "ueb0301"]
LAND_FACTORY_T3: List[str] = LAND_FACTORY_T2[:-1] + ["uel0309", "uel0303", "uel0304"]
AIR_FACTORY_T1: List[str] = ["uea0101", "uea0102", "uea0103", "uea0107", "ueb0202"]
AIR_FACTORY_T2: List[str] = ["uea0101", "uea0102", "uea0103", "uea0107", "uea0204", "uea0203", "ueb0302"]
AIR_FACTORY_T3: List[str] = AIR_FACTORY_T2[:-1] + ["uea0303", "uea0304"]

LAND_UNIT_IDS = {v for k, v in UNITS.items() if v.startswith("uel")}
AIR_UNIT_IDS = {v for k, v in UNITS.items() if v.startswith("uea")}

# Approximate skirt sizes in world units (keeps structures apart when the bot plans placements).
FOOTPRINT: Dict[str, float] = {
    "landFac": 10.0, "airFac": 10.0, "navalFac": 12.0, "landFac2": 10.0, "airFac2": 10.0, "landFac3": 10.0, "airFac3": 10.0,
    "pgen": 4.0, "pgen2": 7.0, "pgen3": 10.0, "mex": 3.0, "mex2": 3.0, "mex3": 3.0, "hydro": 6.0, "massStorage": 3.0,
    "energyStorage": 3.0, "pd": 3.0, "pd2": 4.0, "aa": 3.0, "aa2": 4.0, "aa3": 5.0, "radar": 3.0, "radar2": 3.0, "omni": 4.0,
    "shield2": 5.0, "shield3": 7.0, "wall": 1.0, "tml": 4.0, "tmd": 3.0, "arty2": 5.0, "arty3": 8.0, "airStaging": 4.0,
}

# Strategic icon names (textures/ui/common/game/strategicicons/<name>_rest.dds), used for unit perception on the map.
STRATEGIC_ICON: Dict[str, str] = {
    "acu": "icon_commander_generic", "eng": "icon_land1_engineer", "eng2": "icon_land2_engineer", "eng3": "icon_land3_engineer",
    "landFac": "icon_factory1_land", "landFac2": "icon_factory2_land", "landFac3": "icon_factory3_land",
    "airFac": "icon_factory1_air", "airFac2": "icon_factory2_air", "mex": "icon_structure1_mass", "mex2": "icon_structure2_mass",
    "mex3": "icon_structure3_mass", "pgen": "icon_structure1_energy", "pgen2": "icon_structure2_energy",
    "pgen3": "icon_structure3_energy", "hydro": "icon_structure1_energy", "pd": "icon_structure1_directfire",
    "aa": "icon_structure1_antiair", "radar": "icon_structure1_intel", "tank": "icon_land1_directfire",
    "arty": "icon_land1_artillery", "maa": "icon_land1_antiair", "scout": "icon_land1_intel", "lab": "icon_bot1_directfire",
}


def tier_of(role_or_id: str) -> int:
    """Tech tier of a role name ("pgen2" -> 2) or a blueprint id ("ueb1202" -> 2)."""
    s = role_or_id.lower()
    if s in ROLE_OF_ID:
        s = ROLE_OF_ID[s]
    if s.endswith("3"):
        return 3
    if s.endswith("2") and not s.endswith("m2"):
        return 2
    if s in ("hover2", "mml2", "shield2m", "gunship2", "torpBomber2"):
        return 2
    return 1


def base_role(role: str) -> str:
    """"pgen2" -> "pgen", "tank3" -> "tank"."""
    return role.rstrip("23") if role not in ("shield2m",) else "shield2m"


def structure_id(role: str) -> Optional[str]:
    return STRUCTURES.get(role)


def unit_id(role: str) -> Optional[str]:
    return UNITS.get(role)


def is_structure_id(bp: str) -> bool:
    return bp.lower().startswith("ueb")


def display_name(bp: str) -> str:
    return ROLE_OF_ID.get(bp.lower(), bp)
