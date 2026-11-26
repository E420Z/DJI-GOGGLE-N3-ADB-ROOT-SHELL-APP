"""PC -> goggles screen streaming.

The sender half of `mods/stream`: grabs the Windows desktop, JPEG-encodes it and
pushes length-prefixed frames to `fb_receiver` on the goggles over RNDIS.

Nothing here talks to the device directly - `webapp.py` owns the receiver
start/stop; this module only knows how to produce frames and report stats.
"""
from __future__ import annotations

import io
import socket
import threading
import time

try:
    from PIL import Image, ImageGrab
except Exception:  # pragma: no cover - Pillow is a hard requirement
    Image = None
    ImageGrab = None

SIZES = ["960x540", "1280x720", "1600x900", "1920x1080"]
DEFAULT_SIZE = "1280x720"
DEFAULT_FPS = 12.0
DEFAULT_QUALITY = 65


class PcStream:
    def __init__(self, note=None):
        self._note = note or (lambda _m: None)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.running = False
        self.host = "192.168.60.2"
        self.port = 5570
        self.width = 1280
        self.height = 720
        self.fps = DEFAULT_FPS
        self.quality = DEFAULT_QUALITY

        self.frames = 0
        self.slow = 0
        self.errors = 0
        self.kbps = 0.0
        self.real_fps = 0.0
        self.last_error = ""
        self._t0 = 0.0
        self._window_frames = 0
        self._window_bytes = 0
        self._window_t = 0.0

    # ------------------------------------------------------------------ config
    def configure(self, size=None, fps=None, quality=None) -> None:
        if size:
            try:
                w, h = (int(v) for v in str(size).lower().split("x"))
                if 160 <= w <= 1920 and 90 <= h <= 1080:
                    self.width, self.height = w, h
            except Exception:  # noqa: BLE001
                pass
        if fps:
            self.fps = max(1.0, min(float(fps), 60.0))
        if quality:
            self.quality = max(20, min(int(quality), 95))

    # ------------------------------------------------------------------ lifecycle
    def start(self, size=None, fps=None, quality=None, host=None, port=None) -> bool:
        if self.running:
            return True
        if ImageGrab is None:
            self.last_error = "Pillow is not installed"
            return False
        self.configure(size, fps, quality)
        if host:
            self.host = host
        if port:
            self.port = int(port)

        self._stop.clear()
        self.frames = self.slow = self.errors = 0
        self._t0 = self._window_t = time.time()
        self._window_frames = self._window_bytes = 0
        self._thread = threading.Thread(target=self._run, name="pcstream", daemon=True)
        self._thread.start()
        self.running = True
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self.running = False

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        sock = None
        interval = 1.0 / self.fps
        try:
            sock = socket.create_connection((self.host, self.port), timeout=8)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)
            self._note("pcstream: connected to %s:%d" % (self.host, self.port))
        except Exception as exc:  # noqa: BLE001
            self.last_error = "connect: %s" % exc
            self.errors += 1
            self._note("pcstream: %s" % self.last_error)
            self.running = False
            return

        try:
            while not self._stop.is_set():
                tick = time.time()
                try:
                    im = ImageGrab.grab().convert("RGB")
                except Exception as exc:  # noqa: BLE001
                    self.last_error = "grab: %s" % exc
                    self.errors += 1
                    time.sleep(0.2)
                    continue

                im.thumbnail((self.width, self.height), Image.BILINEAR)
                if im.size != (self.width, self.height):
                    canvas = Image.new("RGB", (self.width, self.height), (0, 0, 0))
                    canvas.paste(im, ((self.width - im.size[0]) // 2,
                                      (self.height - im.size[1]) // 2))
                    im = canvas

                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=self.quality)
                data = buf.getvalue()
                try:
                    sock.sendall(len(data).to_bytes(4, "little") + data)
                except OSError as exc:
                    self.last_error = "send: %s" % exc
                    self.errors += 1
                    break

                with self._lock:
                    self.frames += 1
                    self._window_frames += 1
                    self._window_bytes += len(data)

                spent = time.time() - tick
                if spent > interval:
                    with self._lock:
                        self.slow += 1
                else:
                    self._stop.wait(interval - spent)

                now = time.time()
                if now - self._window_t >= 1.0:
                    with self._lock:
                        self.real_fps = self._window_frames / (now - self._window_t)
                        self.kbps = (self._window_bytes / 1024.0) / (now - self._window_t)
                        self._window_frames = 0
                        self._window_bytes = 0
                        self._window_t = now
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            self.running = False
            self.real_fps = 0.0
            self._note("pcstream: sender stopped")

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "size": "%dx%d" % (self.width, self.height),
                "fps_target": round(self.fps, 1),
                "quality": self.quality,
                "frames": self.frames,
                "slow": self.slow,
                "errors": self.errors,
                "fps": round(self.real_fps, 1),
                "kbps": round(self.kbps, 0),
                "host": self.host,
                "port": self.port,
                "last_error": self.last_error,
            }
