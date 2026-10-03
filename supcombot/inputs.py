"""Mouse and keyboard input via SendInput (scancodes), which DirectX games accept.

All coordinates are absolute screen pixels. A shared `abort` flag makes long sequences stop
immediately when the user switches the bot off.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from typing import Optional

IS_WINDOWS = os.name == "nt"

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# Virtual-key codes for the keys we use.
VK = {
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "escape": 0x1B, "esc": 0x1B, "space": 0x20,
    "enter": 0x0D, "tab": 0x09, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "delete": 0x2E, "insert": 0x2D,
}
for _i in range(10):
    VK[str(_i)] = 0x30 + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = 0x41 + ord(_c) - ord("a")
for _f in range(1, 13):
    VK[f"f{_f}"] = 0x70 + _f - 1

EXTENDED = {"home", "end", "pageup", "pagedown", "left", "up", "right", "down", "delete", "insert"}

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]

    def _send(*inputs) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

    def _mouse_input(dx=0, dy=0, data=0, flags=0) -> "INPUT":
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
        return inp

    def _key_input(vk: int, up: bool, extended: bool) -> "INPUT":
        scan = user32.MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE
        if up:
            flags |= KEYEVENTF_KEYUP
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(0, scan, flags, 0, 0)
        return inp


class AbortedError(RuntimeError):
    pass


class Inputs:
    """Thread-safe-ish input sender. `dry_run` only logs; `abort` stops sequences."""

    def __init__(self, click_delay: float = 0.08, action_delay: float = 0.25, dry_run: bool = False, logger=None) -> None:
        self.click_delay = click_delay
        self.action_delay = action_delay
        self.dry_run = dry_run or not IS_WINDOWS
        self.abort = threading.Event()
        self.log = logger
        self._held: list[str] = []
        self.last_pos = None          # last cursor position set by the bot (user-activity detection)
        self.last_move_time = 0.0
        if IS_WINDOWS:
            self._vx, self._vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            self._vw, self._vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)

    # ----------------------------------------------------------------------------- helpers
    def _check(self) -> None:
        if self.abort.is_set():
            self.release_all()
            raise AbortedError("Eingabe abgebrochen")

    def sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self._check()
            time.sleep(min(0.02, max(0.0, end - time.time())))

    def _dbg(self, msg: str) -> None:
        if self.log:
            self.log.debug("input: %s", msg)

    # ----------------------------------------------------------------------------- mouse
    def move(self, x: int, y: int) -> None:
        self._check()
        self._dbg(f"move {x},{y}")
        self.last_pos = (int(x), int(y))
        self.last_move_time = time.time()
        if self.dry_run:
            return
        ax = int((x - self._vx) * 65535 / max(1, self._vw - 1))
        ay = int((y - self._vy) * 65535 / max(1, self._vh - 1))
        _send(_mouse_input(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))

    def click(self, x: int, y: int, button: str = "left", shift: bool = False, modifier: Optional[str] = None) -> None:
        self._check()
        mods = []
        if shift:
            mods.append("shift")
        if modifier:
            mods.append(modifier)
        self._dbg(f"click {button} {x},{y} mods={mods}")
        self.move(x, y)
        self.sleep(0.03)
        for m in mods:
            self.key_down(m)
        if not self.dry_run:
            down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
            up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
            _send(_mouse_input(0, 0, 0, down))
            time.sleep(self.click_delay / 2)
            _send(_mouse_input(0, 0, 0, up))
        self.sleep(self.click_delay)
        for m in reversed(mods):
            self.key_up(m)

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y)
        self.sleep(0.05)
        self.click(x, y)

    def drag(self, x1: int, y1: int, x2: int, y2: int, steps: int = 8) -> None:
        """Left-drag (box selection)."""
        self._check()
        self._dbg(f"drag {x1},{y1} -> {x2},{y2}")
        self.move(x1, y1)
        self.sleep(0.05)
        if not self.dry_run:
            _send(_mouse_input(0, 0, 0, MOUSEEVENTF_LEFTDOWN))
        for i in range(1, steps + 1):
            self.move(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
            self.sleep(0.02)
        if not self.dry_run:
            _send(_mouse_input(0, 0, 0, MOUSEEVENTF_LEFTUP))
        self.sleep(self.click_delay)

    def wheel(self, notches: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Positive = zoom in (wheel up), negative = zoom out."""
        self._check()
        if x is not None and y is not None:
            self.move(x, y)
            self.sleep(0.03)
        self._dbg(f"wheel {notches}")
        if self.dry_run:
            return
        step = 120 if notches > 0 else -120
        for _ in range(abs(notches)):
            _send(_mouse_input(0, 0, ctypes.c_ulong(step & 0xFFFFFFFF).value, MOUSEEVENTF_WHEEL))
            time.sleep(0.012)
            self._check()

    # ----------------------------------------------------------------------------- keyboard
    def key_down(self, key: str) -> None:
        key = key.lower()
        self._dbg(f"keydown {key}")
        if key not in self._held:
            self._held.append(key)
        if self.dry_run:
            return
        _send(_key_input(VK[key], False, key in EXTENDED))

    def key_up(self, key: str) -> None:
        key = key.lower()
        self._dbg(f"keyup {key}")
        if key in self._held:
            self._held.remove(key)
        if self.dry_run:
            return
        _send(_key_input(VK[key], True, key in EXTENDED))

    def press(self, key: str, times: int = 1) -> None:
        for _ in range(times):
            self._check()
            self.key_down(key)
            time.sleep(0.03)
            self.key_up(key)
            self.sleep(0.05)

    def hotkey(self, *keys: str) -> None:
        for k in keys:
            self.key_down(k)
            time.sleep(0.02)
        for k in reversed(keys):
            self.key_up(k)
            time.sleep(0.02)

    def release_all(self) -> None:
        for k in list(self._held):
            try:
                self.key_up(k)
            except Exception:
                pass
        if not self.dry_run:
            _send(_mouse_input(0, 0, 0, MOUSEEVENTF_LEFTUP))
            _send(_mouse_input(0, 0, 0, MOUSEEVENTF_RIGHTUP))
