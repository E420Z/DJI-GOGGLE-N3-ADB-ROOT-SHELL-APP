"""Synthetic solid-colour sender for the PC -> goggles H.264 path.

Cycles red, green, blue, yellow, cyan, magenta, white, black through the same
NVENC -> TCP -> vendor decoder -> extra_blending sink used by the desktop
stream. Use it to tell a pipeline colour bug from a dark desktop / 4:2:0
chroma-fringing issue.
"""

from __future__ import annotations

import socket
import struct
import threading
import time

import numpy as np

COLORS = [
    ("red", (0, 0, 255)),
    ("green", (0, 255, 0)),
    ("blue", (255, 0, 0)),
    ("yellow", (0, 255, 255)),
    ("cyan", (255, 255, 0)),
    ("magenta", (255, 0, 255)),
    ("white", (255, 255, 255)),
    ("black", (0, 0, 0)),
]


class ColorSender:
    def __init__(self):
        self.frames = 0
        self.bytes = 0
        self.fps = 0.0
        self.kbps = 0.0
        self.running = False
        self.last_error = ""
        self.color = ""
        self._stop = threading.Event()
        self._thread = None
        self._sock = None

    def start(self, host: str, port: int = 5572, width: int = 1920,
              height: int = 1080, fps: int = 60,
              bitrate: int = 20_000_000, hold: float = 1.5) -> bool:
        if self.running:
            return True
        try:
            import av
        except Exception as exc:  # noqa: BLE001
            self.last_error = "PyAV not installed: %s" % exc
            return False
        try:
            codec = av.CodecContext.create("h264_nvenc", "w")
            codec.width = width
            codec.height = height
            codec.pix_fmt = "yuv420p"
            codec.framerate = fps
            codec.bit_rate = bitrate
            codec.options = {"preset": "p1", "tune": "ll", "bf": "0",
                             "g": str(max(fps, 1)), "rc": "cbr",
                             "delay": "0", "zerolatency": "1"}
            codec.open()
            sock = socket.create_connection((host, port), timeout=4)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 18)
            self._av = av
            self._codec = codec
            self._sock = sock
            self._width, self._height = width, height
            self._fps = max(fps, 1)
            self._hold_frames = max(1, int(self._fps * hold))
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self.running = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.stop()
            return False

    def _frame(self, n: int):
        w, h = self._width, self._height
        name, (b, g, r) = COLORS[(n // self._hold_frames) % len(COLORS)]
        self.color = name
        frame = np.empty((h, w, 4), dtype=np.uint8)
        frame[..., 0] = b
        frame[..., 1] = g
        frame[..., 2] = r
        frame[..., 3] = 255
        # moving white marker proves it is live, not a frozen frame
        x = (n * 8) % max(1, w - 140)
        frame[h - 90:h, x:x + 140] = (255, 255, 255, 255)
        return frame

    def _loop(self):
        av = self._av
        last_t = time.time()
        last_f = last_b = 0
        while not self._stop.is_set():
            try:
                frame = self._frame(self.frames)
                vf = av.VideoFrame.from_ndarray(frame, format="bgra")
                vf = vf.reformat(format="yuv420p")
                for pkt in self._codec.encode(vf):
                    data = bytes(pkt)
                    if data:
                        data = struct.pack("<I", len(data)) + data
                        self._sock.sendall(data)
                        self.bytes += len(data)
                        self.frames += 1
                now = time.time()
                if now - last_t >= 1.0:
                    dt = now - last_t
                    self.fps = (self.frames - last_f) / dt
                    self.kbps = (self.bytes - last_b) * 8.0 / 1000.0 / dt
                    last_t, last_f, last_b = now, self.frames, self.bytes
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set():
                    self.last_error = str(exc)
                break
        self.running = False

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.running = False

    def stats(self):
        return {
            "running": self.running,
            "size": "%dx%d" % (self._width, self._height),
            "frames": self.frames,
            "bitrate": 20_000_000,
            "fps": round(self.fps, 1),
            "kbps": int(self.kbps),
            "color": self.color,
            "last_error": self.last_error,
        }
