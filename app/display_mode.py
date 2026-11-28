"""Switch the primary Windows display for 1080p capture, and restore it.

Used by the PC -> Goggles page: before Start the app can switch the desktop to
1920x1080 @ 60 Hz (native capture, no scaling) and restore the saved mode when
the tunnel stops. The saved original lives in app/state/display_mode.json.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(APP_DIR, "state")
SAVE = os.path.join(STATE_DIR, "display_mode.json")
TARGET_W, TARGET_H, TARGET_HZ = 1920, 1080, 60
_IS_WIN = sys.platform.startswith("win")


class _DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short),
        ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short),
        ("dmPrintQuality", ctypes.c_short),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


_DM_BITSPERPEL = 0x00040000
_DM_PELSWIDTH = 0x00080000
_DM_PELSHEIGHT = 0x00100000
_DM_DISPLAYFREQUENCY = 0x00400000


def _user32():
    return ctypes.windll.user32


def current() -> dict:
    """Return {'w','h','hz'} for the primary display, or {} on failure."""
    if not _IS_WIN:
        return {}
    try:
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(dm)
        if not _user32().EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
            return {}
        return {"w": int(dm.dmPelsWidth), "h": int(dm.dmPelsHeight),
                "hz": int(dm.dmDisplayFrequency)}
    except Exception:  # noqa: BLE001
        return {}


def set_mode(w: int, h: int, hz: int = 60) -> int:
    """Apply a display mode; 0 = success (DISP_CHANGE_SUCCESSFUL)."""
    if not _IS_WIN:
        return -1
    try:
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(dm)
        dm.dmFields = (_DM_PELSWIDTH | _DM_PELSHEIGHT | _DM_BITSPERPEL |
                       _DM_DISPLAYFREQUENCY)
        dm.dmPelsWidth = int(w)
        dm.dmPelsHeight = int(h)
        dm.dmBitsPerPel = 32
        dm.dmDisplayFrequency = int(hz)
        return int(_user32().ChangeDisplaySettingsW(ctypes.byref(dm), 0))
    except Exception:  # noqa: BLE001
        return -1


def is_target() -> bool:
    c = current()
    return c.get("w") == TARGET_W and c.get("h") == TARGET_H


def saved() -> dict | None:
    """The original mode saved before a switch, if any."""
    try:
        with open(SAVE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if m.get("w") and m.get("h"):
            return {"w": int(m["w"]), "h": int(m["h"]),
                    "hz": int(m.get("hz") or 60)}
    except Exception:  # noqa: BLE001
        pass
    return None


def save_original() -> dict | None:
    """Save the current mode once; return the saved original."""
    have = saved()
    if have:
        return have
    c = current()
    if not c:
        return None
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SAVE, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=2)
        return c
    except Exception:  # noqa: BLE001
        return None


def ensure_1080() -> tuple[bool, dict | None]:
    """Switch to 1920x1080@60 if needed. Returns (switched, saved_original)."""
    if is_target():
        return False, saved()
    orig = save_original()
    rc = set_mode(TARGET_W, TARGET_H, TARGET_HZ)
    return (rc == 0), orig


def restore() -> dict | None:
    """Restore the saved original mode. Returns it on success, else None."""
    m = saved()
    if not m:
        return None
    rc = set_mode(m["w"], m["h"], m.get("hz") or 60)
    return m if rc == 0 else None
