"""Read-only access to the Steam installation of Forged Alliance.

The game ships everything the bot needs to recognise its own UI:

* ``gamedata/textures.scd`` (a zip): unit build icons ``/textures/ui/common/icons/units/<id>_icon.dds`` and the
  strategic icons drawn on the map at full zoom-out.
* ``gamedata/units.scd``: unit blueprints (categories and ``BuildIconSortPriority`` decide the build menu order).
* ``gamedata/lua.scd``: ``lua/keymap/defaultKeyMap.lua`` (default hotkeys); the player's own bindings live in
  ``%LOCALAPPDATA%\\Gas Powered Games\\Supreme Commander Forged Alliance\\Game.prefs``.

Nothing is written to the game, nothing is injected: the bot only reads files, like a wiki would.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np

from . import uef
from .log import get

log = get("gamefiles")

SORT_GROUPS = ["SORTCONSTRUCTION", "SORTECONOMY", "SORTDEFENSE", "SORTSTRATEGIC", "SORTINTEL", "SORTOTHER"]


def prefs_path() -> Optional[Path]:
    if os.name != "nt":
        return None
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    p = base / "Gas Powered Games" / "Supreme Commander Forged Alliance" / "Game.prefs"
    return p if p.exists() else None


class Blueprint:
    def __init__(self, bp_id: str, categories: Set[str], sort: int, name: str, skirt: Optional[float], buildable: List[str]) -> None:
        self.id = bp_id
        self.categories = categories
        self.sort = sort
        self.name = name
        self.skirt = skirt
        self.buildable = buildable  # Economy.BuildableCategory expressions


class GameFiles:
    """Lazy, cached access to the scd archives. Every accessor returns None when the files are unavailable."""

    def __init__(self, game_dir: Optional[Path]) -> None:
        self.game_dir = Path(game_dir) if game_dir else None
        self._zips: Dict[str, Optional[zipfile.ZipFile]] = {}
        self._index: Dict[str, Dict[str, str]] = {}
        self._icon_cache: Dict[str, Optional[np.ndarray]] = {}
        self._bp_cache: Dict[str, Optional[Blueprint]] = {}
        self._keymap: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------ archives
    def available(self) -> bool:
        return bool(self.game_dir) and (self.game_dir / "gamedata").is_dir()

    def _zip(self, name: str) -> Optional[zipfile.ZipFile]:
        if name in self._zips:
            return self._zips[name]
        z = None
        if self.game_dir:
            p = self.game_dir / "gamedata" / name
            if p.exists():
                try:
                    z = zipfile.ZipFile(p)
                    self._index[name] = {n.lower().replace("\\", "/"): n for n in z.namelist()}
                except Exception as exc:
                    log.warning("%s nicht lesbar: %s", p, exc)
                    z = None
        self._zips[name] = z
        return z

    def read(self, archive: str, path: str) -> Optional[bytes]:
        z = self._zip(archive)
        if z is None:
            return None
        key = path.lower().lstrip("/").replace("\\", "/")
        name = self._index.get(archive, {}).get(key)
        if name is None:
            return None
        try:
            return z.read(name)
        except Exception as exc:
            log.debug("%s/%s: %s", archive, path, exc)
            return None

    def find(self, archive: str, suffix: str) -> List[str]:
        self._zip(archive)
        suffix = suffix.lower()
        return [n for k, n in self._index.get(archive, {}).items() if k.endswith(suffix)]

    # ------------------------------------------------------------------ textures
    def _dds(self, archive: str, path: str) -> Optional[np.ndarray]:
        data = self.read(archive, path)
        if not data:
            return None
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data)).convert("RGBA")
            return np.asarray(img)
        except Exception as exc:
            log.debug("DDS %s nicht dekodierbar: %s", path, exc)
            return None

    def unit_icon(self, bp_id: str) -> Optional[np.ndarray]:
        """RGBA build icon of a unit (64x64 or 48x48 in the game files)."""
        bp_id = bp_id.lower()
        if bp_id not in self._icon_cache:
            self._icon_cache[bp_id] = self._dds("textures.scd", f"textures/ui/common/icons/units/{bp_id}_icon.dds")
        return self._icon_cache[bp_id]

    def strategic_icon(self, name: str, variant: str = "rest") -> Optional[np.ndarray]:
        key = f"strat:{name}:{variant}"
        if key not in self._icon_cache:
            self._icon_cache[key] = self._dds("textures.scd", f"textures/ui/common/game/strategicicons/{name}_{variant}.dds")
        return self._icon_cache[key]

    def ui_texture(self, path: str) -> Optional[np.ndarray]:
        """Any UI texture by its game path, e.g. /textures/ui/common/game/avatar/avatar_bmp.dds."""
        return self._dds("textures.scd", path)

    # ------------------------------------------------------------------ blueprints
    def blueprint(self, bp_id: str) -> Optional[Blueprint]:
        bp_id = bp_id.lower()
        if bp_id in self._bp_cache:
            return self._bp_cache[bp_id]
        bp = None
        data = self.read("units.scd", f"units/{bp_id}/{bp_id}_unit.bp")
        if data:
            try:
                bp = parse_blueprint(bp_id, data.decode("utf-8", errors="ignore"))
            except Exception as exc:
                log.debug("Blueprint %s: %s", bp_id, exc)
        self._bp_cache[bp_id] = bp
        return bp

    def menu_order(self, ids: List[str]) -> List[str]:
        """Order in which the construction panel shows these blueprints (vanilla sorting)."""
        groups: Dict[str, List[str]] = {g: [] for g in SORT_GROUPS}
        misc: List[str] = []
        for i in ids:
            bp = self.blueprint(i)
            cats = bp.categories if bp else set()
            for g in SORT_GROUPS:
                if g in cats:
                    groups[g].append(i)
                    break
            else:
                misc.append(i)

        def key(i: str):
            bp = self.blueprint(i)
            return (bp.sort if bp else 1000, i)

        out: List[str] = []
        for g in SORT_GROUPS:
            out += sorted(groups[g], key=key)
        out += sorted(misc, key=key)
        return out

    def buildable_by(self, builder_id: str, candidates: List[str]) -> List[str]:
        """Which of the candidates the builder can produce, according to the blueprint categories."""
        builder = self.blueprint(builder_id)
        if not builder or not builder.buildable:
            return list(candidates)
        exprs = [set(e.upper().split()) for e in builder.buildable]
        out = []
        for c in candidates:
            bp = self.blueprint(c)
            if not bp:
                continue
            if any(req <= bp.categories for req in exprs):
                out.append(c)
        return out

    # ------------------------------------------------------------------ keymap
    def keymap(self) -> Dict[str, str]:
        """action -> key combo ('Ctrl-A', 'Comma', ...). Game defaults overlaid with the player's own bindings."""
        if self._keymap is not None:
            return self._keymap
        km: Dict[str, str] = {}
        data = self.read("lua.scd", "lua/keymap/defaultKeyMap.lua")
        if data:
            for k, a in parse_keymap(data.decode("utf-8", errors="ignore")).items():
                km[a] = k
        p = prefs_path()
        if p:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                user = parse_user_keymap(text)
                for k, a in user.items():
                    km[a] = k
                if user:
                    log.info("Eigene Tastenbelegung aus Game.prefs uebernommen (%d Eintraege)", len(user))
            except OSError:
                pass
        self._keymap = km
        return km

    def key_for(self, action: str) -> Optional[str]:
        return self.keymap().get(action)


# ---------------------------------------------------------------------------------------------- parsing helpers
_CAT_BLOCK = re.compile(r"Categories\s*=\s*\{(.*?)\}", re.S)
_STR = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_BUILDABLE = re.compile(r"BuildableCategory\s*=\s*\{(.*?)\}", re.S)
_KEY_ENTRY = re.compile(r"\[\s*['\"]([^'\"]+)['\"]\s*\]\s*=\s*['\"]([^'\"]+)['\"]")


def parse_blueprint(bp_id: str, text: str) -> Blueprint:
    cats: Set[str] = set()
    m = _CAT_BLOCK.search(text)
    if m:
        for s in _STR.finditer(m.group(1)):
            cats.add((s.group(1) or s.group(2) or "").upper())
    m = re.search(r"BuildIconSortPriority\s*=\s*(\d+)", text)
    if m:
        sort = int(m.group(1))
    else:
        m = re.search(r"StrategicIconSortPriority\s*=\s*(\d+)", text)
        sort = int(m.group(1)) if m else 1000
    m = re.search(r"UnitName\s*=\s*['\"](?:<LOC [^>]*>)?([^'\"]*)['\"]", text)
    name = m.group(1) if m else bp_id
    m = re.search(r"SkirtSizeX\s*=\s*([\d.]+)", text)
    skirt = float(m.group(1)) if m else None
    buildable: List[str] = []
    m = _BUILDABLE.search(text)
    if m:
        for s in _STR.finditer(m.group(1)):
            buildable.append(s.group(1) or s.group(2) or "")
    return Blueprint(bp_id, cats, sort, name, skirt, buildable)


def parse_keymap(text: str) -> Dict[str, str]:
    """['Ctrl-A'] = 'select_air' lines -> {key: action}. Comments are ignored."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("--", 1)[0]
        for m in _KEY_ENTRY.finditer(line):
            out[m.group(1)] = m.group(2)
    return out


def parse_user_keymap(text: str) -> Dict[str, str]:
    """The UserKeyMap table of Game.prefs (only present when the player changed bindings)."""
    idx = text.find("UserKeyMap")
    if idx < 0:
        return {}
    start = text.find("{", idx)
    if start < 0:
        return {}
    depth, i = 0, start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return parse_keymap(text[start:i + 1])


def parse_prefs_resolution(text: str) -> Optional[tuple]:
    m = re.search(r"primary\s*=\s*\{[^}]*width\s*=\s*(\d+)[^}]*height\s*=\s*(\d+)", text, re.S)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None
