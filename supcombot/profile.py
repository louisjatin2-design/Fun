"""UI calibration profiles: screen positions of game buttons, bars and reference patches.

A profile is bound to a faction and a client resolution. Points are stored in client coordinates
(relative to the game window's client area) so a moved window keeps working.
"""
from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import config

# (key, German instruction, store reference patch?, required?)
CALIBRATION_STEPS: List[Tuple[str, str, bool, bool]] = [
    ("ui.exclude.top", "UI-Ausschluss: Zeige auf die UNTERE Kante der oberen Leiste (Wirtschaftsanzeige) am linken Bildrand.", False, True),
    ("ui.exclude.right", "UI-Ausschluss: Zeige auf die LINKE Kante der rechten Avatar-Spalte (ACU-Portrait) in Bildschirmmitte-Hoehe.", False, True),
    ("ui.exclude.bottom", "UI-Ausschluss: Waehle den ACU, dann zeige auf die OBERE Kante des Baumenues unten.", False, True),
    ("ui.idle_engineer", "Lass einen Ingenieur untaetig stehen. Zeige auf das Idle-Ingenieur-Symbol (rechte Avatar-Leiste).", True, True),
    ("ui.idle_factory", "Lass eine Fabrik untaetig stehen. Zeige auf das Idle-Fabrik-Symbol (rechte Avatar-Leiste). (Optional: F7 ueberspringt)", True, False),
    ("ui.build.landFac", "ACU/Ingenieur ausgewaehlt, Baumenue T1: zeige auf LANDFABRIK.", True, True),
    ("ui.build.airFac", "Baumenue T1: zeige auf LUFTFABRIK.", True, True),
    ("ui.build.pgen", "Baumenue T1: zeige auf ENERGIEGENERATOR (T1).", True, True),
    ("ui.build.mex", "Baumenue T1: zeige auf MASSENEXTRAKTOR (T1).", True, True),
    ("ui.build.hydro", "Baumenue T1: zeige auf HYDROKARBON-KRAFTWERK. (Optional)", True, False),
    ("ui.build.massStorage", "Baumenue T1: zeige auf MASSENSPEICHER. (Optional)", True, False),
    ("ui.build.pd", "Baumenue T1: zeige auf PUNKTVERTEIDIGUNG (T1). (Optional)", True, False),
    ("ui.build.aa", "Baumenue T1: zeige auf FLAK/LUFTABWEHR (T1). (Optional)", True, False),
    ("ui.build.radar", "Baumenue T1: zeige auf RADAR (T1). (Optional)", True, False),
    ("ui.build.tab_t1", "Baumenue: zeige auf den Reiter T1. (Optional, hilft beim Zurueckschalten)", True, False),
    ("ui.build.tab_t2", "Baumenue: zeige auf den Reiter T2 (nur verfuegbar mit T2-Ingenieur). (Optional)", True, False),
    ("ui.build.pgen2", "Baumenue T2 (T2-Ingenieur): zeige auf ENERGIEGENERATOR T2. (Optional)", True, False),
    ("ui.build.pd2", "Baumenue T2: zeige auf PUNKTVERTEIDIGUNG T2. (Optional)", True, False),
    ("ui.build.aa2", "Baumenue T2: zeige auf FLAK T2. (Optional)", True, False),
    ("ui.build.shield2", "Baumenue T2: zeige auf SCHILD T2. (Optional)", True, False),
    ("ui.build.tab_t3", "Baumenue: zeige auf den Reiter T3 (nur mit T3-Ingenieur). (Optional)", True, False),
    ("ui.build.pgen3", "Baumenue T3 (T3-Ingenieur): zeige auf ENERGIEGENERATOR T3. (Optional)", True, False),
    ("ui.build.pd3", "Baumenue T3: zeige auf schwere PUNKTVERTEIDIGUNG T3 (falls vorhanden). (Optional)", True, False),
    ("ui.build.aa3", "Baumenue T3: zeige auf FLAK/SAM T3. (Optional)", True, False),
    ("ui.factory.land.eng", "Landfabrik ausgewaehlt: zeige auf INGENIEUR.", True, True),
    ("ui.factory.land.tank", "Landfabrik: zeige auf PANZER (T1 Haupt-Kampfeinheit).", True, True),
    ("ui.factory.land.arty", "Landfabrik: zeige auf ARTILLERIE (T1). (Optional)", True, False),
    ("ui.factory.land.maa", "Landfabrik: zeige auf MOBILE FLAK (T1). (Optional)", True, False),
    ("ui.factory.land.scout", "Landfabrik: zeige auf SPAEHER (T1). (Optional)", True, False),
    ("ui.factory.air.scout", "Luftfabrik ausgewaehlt: zeige auf LUFT-SPAEHER. (Optional)", True, False),
    ("ui.factory.air.inter", "Luftfabrik: zeige auf ABFANGJAEGER. (Optional)", True, False),
    ("ui.factory.air.bomber", "Luftfabrik: zeige auf BOMBER. (Optional)", True, False),
    ("ui.upgrade", "Massenextraktor ausgewaehlt: zeige auf den UPGRADE-Button im Baumenue. (Optional)", True, False),
    ("ui.factory.upgrade", "Landfabrik ausgewaehlt: zeige auf den UPGRADE-Button (T2-Hauptquartier). (Optional)", True, False),
    ("ui.factory.repeat", "Fabrik ausgewaehlt: zeige auf den Button WIEDERHOLEN/Endlosschleife. (Optional)", True, False),
    ("ui.factory.tab_t2", "T2-Fabrik ausgewaehlt: zeige auf den Reiter T2 im Fabrikmenue. (Optional)", True, False),
    ("ui.factory.land.eng2", "T2-Landfabrik, Reiter T2: zeige auf T2-INGENIEUR. (Optional)", True, False),
    ("ui.factory.land.tank2", "T2-Landfabrik, Reiter T2: zeige auf T2-PANZER. (Optional)", True, False),
    ("ui.factory.land.maa2", "T2-Landfabrik, Reiter T2: zeige auf MOBILE FLAK T2. (Optional)", True, False),
    ("ui.factory.upgrade3", "T2-Landfabrik ausgewaehlt: zeige auf den UPGRADE-Button auf T3. (Optional)", True, False),
    ("ui.factory.tab_t3", "T3-Fabrik ausgewaehlt: zeige auf den Reiter T3 im Fabrikmenue. (Optional)", True, False),
    ("ui.factory.land.eng3", "T3-Landfabrik, Reiter T3: zeige auf T3-INGENIEUR. (Optional)", True, False),
    ("ui.factory.land.tank3", "T3-Landfabrik, Reiter T3: zeige auf T3-PANZER/SCHWERE EINHEIT. (Optional)", True, False),
    ("ui.factory.land.arty3", "T3-Landfabrik, Reiter T3: zeige auf MOBILE ARTILLERIE T3. (Optional)", True, False),
    ("ui.factory.air.inter3", "T3-Luftfabrik, Reiter T3: zeige auf LUFTUEBERLEGENHEITSJAEGER T3. (Optional)", True, False),
    ("ui.factory.air.bomber3", "T3-Luftfabrik, Reiter T3: zeige auf STRATEGISCHEN BOMBER T3. (Optional)", True, False),
    ("ui.upgrade3", "T2-Massenextraktor ausgewaehlt: zeige auf den UPGRADE-Button auf T3. (Optional)", True, False),
    ("ui.eco.mass_left", "Zeige auf das LINKE Ende der MASSE-Speicherleiste (oben).", False, True),
    ("ui.eco.mass_right", "Zeige auf das RECHTE Ende der MASSE-Speicherleiste.", False, True),
    ("ui.eco.energy_left", "Zeige auf das LINKE Ende der ENERGIE-Speicherleiste.", False, True),
    ("ui.eco.energy_right", "Zeige auf das RECHTE Ende der ENERGIE-Speicherleiste.", False, True),
    ("colors.team", "Volle Zoomstufe heraus (Mausrad). Zeige auf das Symbol DEINES ACU (Teamfarbe wird gesampelt).", False, True),
    ("colors.enemy", "Optional: zeige (ganz herausgezoomt) auf das Symbol einer GEGNER-Einheit oder eines Gegner-Gebaeudes. Mehrere Gegnerfarben: Schritt mit --only colors.enemy wiederholen.", False, False),
]


def _encode_patch(patch: np.ndarray) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(patch).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_patch(data: str) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB"))


@dataclass
class Profile:
    faction: str
    resolution: Tuple[int, int]
    points: Dict[str, dict] = field(default_factory=dict)  # key -> {"x","y","patch"?}
    map_rects: Dict[str, List[int]] = field(default_factory=dict)  # map key -> [x,y,w,h] (client coords)
    team_color: Optional[List[int]] = None
    enemy_colors: List[List[int]] = field(default_factory=list)
    templates: Dict[str, str] = field(default_factory=dict)  # name -> base64 png (e.g. victory dialog)
    template_pos: Dict[str, List[int]] = field(default_factory=dict)
    calibrated: bool = False
    _patch_cache: Dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def path_for(faction: str, resolution: Tuple[int, int]) -> Path:
        return config.PROFILES_DIR / f"{faction}_{resolution[0]}x{resolution[1]}.json"

    @classmethod
    def load(cls, faction: str, resolution: Tuple[int, int]) -> "Profile":
        p = cls.path_for(faction, resolution)
        prof = cls(faction=faction, resolution=tuple(resolution))
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            prof.points = data.get("points", {})
            prof.map_rects = data.get("map_rects", {})
            prof.team_color = data.get("team_color")
            prof.enemy_colors = data.get("enemy_colors", [])
            prof.templates = data.get("templates", {})
            prof.template_pos = data.get("template_pos", {})
            prof.calibrated = bool(data.get("calibrated", False))
        else:
            # Fall back to the bundled example for this resolution, if any (unverified positions!).
            bundled = config.PACKAGE_DIR / "profiles" / f"{faction}_{resolution[0]}x{resolution[1]}.json"
            if not bundled.exists():
                bundled = config.PACKAGE_DIR / "profiles" / f"default_{resolution[0]}x{resolution[1]}.json"
            if bundled.exists():
                data = json.loads(bundled.read_text(encoding="utf-8"))
                prof.points = data.get("points", {})
                prof.calibrated = False
        return prof

    @classmethod
    def available(cls, resolution: Tuple[int, int]) -> List[Tuple[str, "Profile"]]:
        """All faction profiles for this resolution that have the required points."""
        out = []
        for faction in ("uef", "aeon", "cybran", "seraphim"):
            if cls.path_for(faction, resolution).exists():
                prof = cls.load(faction, resolution)
                if not prof.missing_required():
                    out.append((faction, prof))
        return out

    def copy_from(self, other: "Profile") -> List[str]:
        """Take over everything from another faction's profile; returns the keys whose patches must be re-captured."""
        self.points = {k: dict(v) for k, v in other.points.items()}
        self.map_rects = dict(other.map_rects)
        self.team_color = other.team_color
        self.enemy_colors = list(other.enemy_colors)
        self.templates = dict(other.templates)
        self.template_pos = dict(other.template_pos)
        self._patch_cache = {}
        return [k for k, v in self.points.items() if "patch" in v and (k.startswith("ui.build.") or k.startswith("ui.factory.")
                                                                    or k.startswith("ui.upgrade") or k.startswith("ui.idle_"))]

    def recapture(self, img: np.ndarray, keys: List[str]) -> int:
        """Re-capture the reference patches of the given keys from one screenshot (positions stay)."""
        from . import vision

        n = 0
        for k in keys:
            if self.has(k):
                x, y = self.point(k)
                self.set_point(k, x, y, vision.extract_patch(img, x, y, 24))
                n += 1
        return n

    def save(self) -> None:
        config.ensure_dirs()
        data = {
            "faction": self.faction,
            "resolution": list(self.resolution),
            "calibrated": self.calibrated,
            "points": self.points,
            "map_rects": self.map_rects,
            "team_color": self.team_color,
            "enemy_colors": self.enemy_colors,
            "templates": self.templates,
            "template_pos": self.template_pos,
        }
        p = self.path_for(self.faction, self.resolution)
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")

    # ------------------------------------------------------------------ access
    def has(self, key: str) -> bool:
        return key in self.points

    def point(self, key: str) -> Tuple[int, int]:
        p = self.points[key]
        return int(p["x"]), int(p["y"])

    def set_point(self, key: str, x: int, y: int, patch: Optional[np.ndarray] = None) -> None:
        entry: dict = {"x": int(x), "y": int(y)}
        if patch is not None:
            entry["patch"] = _encode_patch(patch)
            self._patch_cache.pop(key, None)
        self.points[key] = entry

    def patch(self, key: str) -> Optional[np.ndarray]:
        if key in self._patch_cache:
            return self._patch_cache[key]
        p = self.points.get(key)
        if not p or "patch" not in p:
            return None
        arr = _decode_patch(p["patch"])
        self._patch_cache[key] = arr
        return arr

    def set_template(self, name: str, img: np.ndarray, x: int, y: int) -> None:
        self.templates[name] = _encode_patch(img)
        self.template_pos[name] = [int(x), int(y)]

    def template(self, name: str) -> Optional[Tuple[np.ndarray, int, int]]:
        if name not in self.templates:
            return None
        x, y = self.template_pos.get(name, [0, 0])
        return _decode_patch(self.templates[name]), x, y

    def exclude_rects(self) -> List[Tuple[int, int, int, int]]:
        """UI panels to ignore when detecting the map rectangle."""
        w, h = self.resolution
        rects = []
        if self.has("ui.exclude.top"):
            rects.append((0, 0, w, self.point("ui.exclude.top")[1] + 2))
        if self.has("ui.exclude.right"):
            x = self.point("ui.exclude.right")[0] - 2
            rects.append((x, 0, w - x, h))
        if self.has("ui.exclude.bottom"):
            y = self.point("ui.exclude.bottom")[1] - 2
            rects.append((0, y, w, h - y))
        return rects

    def missing_required(self) -> List[str]:
        return [key for key, _i, _p, required in CALIBRATION_STEPS if required and not self.has(key) and not key.startswith("colors.")]
