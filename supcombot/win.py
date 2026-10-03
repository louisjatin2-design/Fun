"""Windows window helpers (ctypes only). Safe to import on other platforms: functions raise RuntimeError."""
from __future__ import annotations

import ctypes
import os
from typing import Optional, Tuple

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def _require() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Diese Funktion ist nur unter Windows verfuegbar.")


def set_dpi_aware() -> None:
    """Make coordinates physical pixels (important on scaled displays)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def window_title(hwnd: int) -> str:
    _require()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_window(title_substring: str) -> Optional[int]:
    """First visible top-level window whose title contains the substring (case-insensitive)."""
    _require()
    needle = title_substring.lower()
    found: list = []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            t = window_title(hwnd)
            if t and needle in t.lower():
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def client_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """Client area in screen coordinates: (left, top, width, height)."""
    _require()
    rc = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def is_foreground(hwnd: int) -> bool:
    _require()
    return user32.GetForegroundWindow() == hwnd


def bring_to_front(hwnd: int) -> None:
    _require()
    user32.SetForegroundWindow(hwnd)


def cursor_pos() -> Tuple[int, int]:
    _require()
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def screen_size() -> Tuple[int, int]:
    _require()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def virtual_screen() -> Tuple[int, int, int, int]:
    """(left, top, width, height) of the virtual desktop (all monitors)."""
    _require()
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77), user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
