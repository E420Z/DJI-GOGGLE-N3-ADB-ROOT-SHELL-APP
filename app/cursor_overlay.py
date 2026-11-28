"""Draw the Windows mouse cursor into a BGRA frame.

DXGI Desktop Duplication (dxcam) does not include the cursor in captured
frames, so the goggles never see it. This module reads the cursor bitmap with
the Win32 API and alpha-blends it onto the frame.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_IS_WIN = sys.platform.startswith("win")


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", _POINT),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class CursorOverlay:
    """Stateful cursor painter; caches the bitmap until the cursor changes."""

    def __init__(self):
        self._ok = False
        self._last_handle = None
        self._bitmap = None       # numpy BGRA array
        self._hot = (0, 0)
        self._size = (0, 0)
        self._screen = (0, 0)
        if not _IS_WIN:
            return
        try:
            import numpy as np  # noqa: F401
            self._np = np
            self._user32 = ctypes.windll.user32
            self._gdi32 = ctypes.windll.gdi32
            self._user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
            self._user32.GetCursorInfo.restype = wintypes.BOOL
            self._user32.GetIconInfo.argtypes = [wintypes.HANDLE,
                                                 ctypes.POINTER(_ICONINFO)]
            self._user32.GetIconInfo.restype = wintypes.BOOL
            self._user32.GetDC.argtypes = [wintypes.HWND]
            self._user32.GetDC.restype = wintypes.HDC
            self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            self._gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p]
            self._gdi32.GetDIBits.argtypes = [
                wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                ctypes.c_void_p, ctypes.POINTER(_BITMAPINFOHEADER),
                wintypes.UINT]
            self._gdi32.GetDIBits.restype = ctypes.c_int
            self._gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            self._screen = (self._user32.GetSystemMetrics(0),
                            self._user32.GetSystemMetrics(1))
            self._ok = True
        except Exception:  # noqa: BLE001
            self._ok = False

    def _read_cursor(self, handle):
        np = self._np
        ii = _ICONINFO()
        if not self._user32.GetIconInfo(handle, ctypes.byref(ii)):
            return None
        try:
            bmp = _BITMAP()
            if not ii.hbmColor:
                return None
            if not self._gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(bmp),
                                          ctypes.byref(bmp)):
                return None
            w, h = int(bmp.bmWidth), int(bmp.bmHeight)
            if w <= 0 or h <= 0 or w > 512 or h > 512:
                return None
            bi = _BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth = w
            bi.biHeight = -h
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            hdc = self._user32.GetDC(None)
            if not hdc:
                return None
            try:
                got = self._gdi32.GetDIBits(hdc, ii.hbmColor, 0, h, buf,
                                            ctypes.byref(bi), 0)
            finally:
                self._user32.ReleaseDC(None, hdc)
            if got != h:
                return None
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4)).copy()
            return arr, (int(ii.xHotspot), int(ii.yHotspot))
        finally:
            if ii.hbmMask:
                self._gdi32.DeleteObject(ii.hbmMask)
            if ii.hbmColor:
                self._gdi32.DeleteObject(ii.hbmColor)

    def _refresh(self, handle):
        res = self._read_cursor(handle)
        self._last_handle = handle
        if res is None:
            self._bitmap = None
            return
        self._bitmap, self._hot = res

    def draw(self, frame) -> None:
        """Blend the current cursor onto a writable BGRA numpy frame."""
        if not self._ok or frame is None:
            return
        np = self._np
        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(ci)
        if not self._user32.GetCursorInfo(ctypes.byref(ci)):
            return
        if not (ci.flags & 0x1):          # CURSOR_SHOWING
            return
        handle = ci.hCursor
        if handle != self._last_handle or self._bitmap is None:
            self._refresh(handle)
        cur = self._bitmap
        if cur is None:
            return
        fh, fw = frame.shape[:2]
        sw, sh = self._screen
        sx = fw / float(sw or fw)
        sy = fh / float(sh or fh)
        h, w = cur.shape[:2]
        cw = max(1, int(round(w * sx)))
        ch = max(1, int(round(h * sy)))
        x = int(round(ci.ptScreenPos.x * sx)) - int(round(self._hot[0] * sx))
        y = int(round(ci.ptScreenPos.y * sy)) - int(round(self._hot[1] * sy))
        if cw != w or ch != h:
            ys = (np.arange(ch) * (h / float(ch))).astype(np.int32)
            xs = (np.arange(cw) * (w / float(cw))).astype(np.int32)
            cur = cur[ys[:, None], xs[None, :]]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(fw, x + cw), min(fh, y + ch)
        if x1 <= x0 or y1 <= y0:
            return
        cx0, cy0 = x0 - x, y0 - y
        src = cur[cy0:cy0 + (y1 - y0), cx0:cx0 + (x1 - x0)]
        roi = frame[y0:y1, x0:x1]
        alpha = src[..., 3:4].astype(np.float32) / 255.0
        if not alpha.any():
            return
        rgb = src[..., :3].astype(np.float32)
        out = rgb * alpha + roi[..., :3].astype(np.float32) * (1.0 - alpha)
        roi[..., :3] = out.astype(np.uint8)
