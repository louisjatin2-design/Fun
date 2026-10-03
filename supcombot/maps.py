"""Map data straight from the Steam install: markers (mass, hydro, start positions), size, preview image.

No in-game access is needed: every map ships `<map>_scenario.lua`, `<map>_save.lua` and `<map>.scmap`.
"""
from __future__ import annotations

import io
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .log import get

log = get("maps")

Vec2 = Tuple[float, float]


@dataclass
class Marker:
    name: str
    kind: str
    x: float
    z: float


@dataclass
class MapInfo:
    folder: Path
    name: str
    size: Tuple[int, int]
    scmap: Optional[Path]
    mass: List[Marker] = field(default_factory=list)
    hydro: List[Marker] = field(default_factory=list)
    starts: Dict[int, Marker] = field(default_factory=dict)
    _preview: Optional[np.ndarray] = None

    @property
    def key(self) -> str:
        return self.folder.name.lower()

    @property
    def aspect(self) -> float:
        return self.size[0] / max(1, self.size[1])

    def preview(self) -> Optional[np.ndarray]:
        if self._preview is None and self.scmap and self.scmap.exists():
            self._preview = load_preview(self.scmap)
        return self._preview

    def start_positions(self) -> List[Tuple[int, Marker]]:
        return sorted(self.starts.items())


# ------------------------------------------------------------------------------------------ discovery
def steam_game_dir() -> Optional[Path]:
    """Locate the Steam install of Forged Alliance (registry + libraryfolders.vdf)."""
    candidates: List[Path] = []
    if os.name == "nt":
        try:
            import winreg  # type: ignore

            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        val = winreg.QueryValueEx(k, "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                        candidates.append(Path(val))
                except OSError:
                    pass
        except ImportError:
            pass
        candidates += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libraries: List[Path] = []
    for steam in candidates:
        libraries.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                    libraries.append(Path(m.group(1).replace("\\\\", "\\")))
            except OSError:
                pass
    for lib in libraries:
        d = lib / "steamapps" / "common" / "Supreme Commander Forged Alliance"
        if (d / "maps").is_dir():
            return d
    return None


def user_maps_dir() -> Optional[Path]:
    if os.name != "nt":
        return None
    docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "My Games" / "Gas Powered Games" / "Supreme Commander Forged Alliance" / "maps"
    return docs if docs.is_dir() else None


def list_maps(game_dir: Optional[Path]) -> List[MapInfo]:
    dirs = []
    if game_dir and (game_dir / "maps").is_dir():
        dirs.append(game_dir / "maps")
    um = user_maps_dir()
    if um:
        dirs.append(um)
    maps: List[MapInfo] = []
    seen = set()
    for d in dirs:
        for folder in sorted(p for p in d.iterdir() if p.is_dir()):
            if folder.name.lower() in seen:
                continue
            try:
                info = load_map(folder)
            except Exception as exc:  # broken custom maps must not kill the listing
                log.debug("Karte %s uebersprungen: %s", folder.name, exc)
                continue
            if info:
                seen.add(folder.name.lower())
                maps.append(info)
    return maps


def find_map(maps: List[MapInfo], query: str) -> Optional[MapInfo]:
    q = query.lower().strip()
    for m in maps:
        if m.key == q or m.name.lower() == q:
            return m
    for m in maps:
        if q in m.key or q in m.name.lower():
            return m
    return None


# ------------------------------------------------------------------------------------------ parsing
_VEC = re.compile(r"VECTOR3\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)")
_MARKER = re.compile(r"\['([^']+)'\]\s*=\s*\{([^{}]*)\}", re.S)


def parse_scenario(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict = {}
    m = re.search(r"\bname\s*=\s*['\"](.*?)['\"]", text)
    out["name"] = m.group(1) if m else path.parent.name
    m = re.search(r"\bsize\s*=\s*\{\s*(\d+)\s*,\s*(\d+)\s*\}", text)
    out["size"] = (int(m.group(1)), int(m.group(2))) if m else (512, 512)
    m = re.search(r"\bmap\s*=\s*['\"](.*?)['\"]", text)
    out["map"] = m.group(1) if m else ""
    m = re.search(r"\bsave\s*=\s*['\"](.*?)['\"]", text)
    out["save"] = m.group(1) if m else ""
    return out


def parse_save_markers(path: Path) -> List[Marker]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    idx = text.find("Markers")
    if idx < 0:
        return []
    section = text[idx:]
    markers: List[Marker] = []
    for m in _MARKER.finditer(section):
        name, body = m.group(1), m.group(2)
        t = re.search(r"\['type'\]\s*=\s*STRING\(\s*'([^']*)'\s*\)", body)
        v = _VEC.search(body)
        if not t or not v:
            continue
        markers.append(Marker(name=name, kind=t.group(1), x=float(v.group(1)), z=float(v.group(3))))
    return markers


def load_map(folder: Path) -> Optional[MapInfo]:
    scen = next(iter(folder.glob("*_scenario.lua")), None)
    if not scen:
        return None
    info = parse_scenario(scen)
    save = next(iter(folder.glob("*_save.lua")), None)
    scmap = next(iter(folder.glob("*.scmap")), None)
    mi = MapInfo(folder=folder, name=info["name"], size=info["size"], scmap=scmap)
    if save:
        for mk in parse_save_markers(save):
            if mk.kind == "Mass":
                mi.mass.append(mk)
            elif mk.kind == "Hydrocarbon":
                mi.hydro.append(mk)
            else:
                am = re.fullmatch(r"ARMY_(\d+)", mk.name)
                if am:
                    mi.starts[int(am.group(1))] = mk
    return mi


def load_preview(scmap: Path) -> Optional[np.ndarray]:
    """Extract the embedded DDS preview of a .scmap (header documented by the FAF map tools)."""
    try:
        with scmap.open("rb") as f:
            head = f.read(30)
            if len(head) < 30 or head[:4] != b"Map\x1a":
                return None
            # int32 magic, int32 major, int32 unknown, int32 unknown, float w, float h, int32 unknown, int16 unknown
            (_magic, _major, _u1, _u2, _w, _h, _u3, _u4) = struct.unpack("<iiiiffih", head)
            (length,) = struct.unpack("<i", f.read(4))
            if length <= 0 or length > 50_000_000:
                return None
            dds = f.read(length)
        from PIL import Image

        img = Image.open(io.BytesIO(dds)).convert("RGB")
        return np.asarray(img)
    except Exception as exc:
        log.debug("Preview von %s nicht lesbar: %s", scmap, exc)
        return None


def match_map(map_image: np.ndarray, maps: List[MapInfo]) -> Tuple[Optional[MapInfo], float]:
    """Pick the map whose preview correlates best with the screenshot of the map area."""
    from .vision import normalized_correlation, resize

    best, best_score = None, -1.0
    probe = resize(map_image, (128, 128))
    for m in maps:
        pv = m.preview()
        if pv is None:
            continue
        score = normalized_correlation(probe, resize(pv, (128, 128)))
        if score > best_score:
            best, best_score = m, score
    return best, best_score
