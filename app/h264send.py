"""Low-latency PC -> goggles H.264 sender (DXGI capture + NVENC).

Output is raw Annex-B H.264 over TCP. The goggles side is expected to listen
and feed AUs to the vendor decoder.

This module is optional: it imports dxcam/PyAV only when started.
"""
from __future__ import annotations

import socket
import struct
import threading
import time

import numpy as np


class H264Sender:
    def __init__(self, note=None):
        self._note = note or (lambda _m: None)
        self._stop = threading.Event()
        self._thread = None
        self._cam = None
        self._sock = None
        self.frames = 0
        self.bytes = 0
        self.fps = 0.0
        self.kbps = 0.0
        self.encode_ms = 0.0
        self.last_error = ""
        self.running = False
        self.size = "1920x1080"
        self.bitrate = 30_000_000
        self.codec = "h264"
        self._cursor = None

    def start(self, host: str, port: int = 5570, width: int = 1920,
              height: int = 1080, fps: int = 60,
              bitrate: int = 30_000_000, region=None,
              framed: bool = True, cursor: bool = True,
              codec: str = "h264") -> bool:
        if self.running:
            return True
        try:
            import av
            import dxcam
        except Exception as exc:  # noqa: BLE001
            self.last_error = "dxcam/PyAV not installed: %s" % exc
            return False
        try:
            self._cam = dxcam.create(output_color="BGRA", region=region)
            self._cam.start(target_fps=fps, video_mode=True)
            enc_name = "hevc_nvenc" if codec == "h265" else "h264_nvenc"
            codec_ctx = av.CodecContext.create(enc_name, "w")
            codec_ctx.width = width
            codec_ctx.height = height
            codec_ctx.pix_fmt = "yuv420p"
            codec_ctx.framerate = fps
            codec_ctx.bit_rate = bitrate
            codec_ctx.options = {"preset": "p1", "tune": "ull", "bf": "0",
                                 "g": str(max(fps, 1)), "rc": "cbr",
                                 "delay": "0", "zerolatency": "1",
                                 "aud": "1", "repeat_headers": "1",
                                 "spatial_aq": "1", "temporal_aq": "1",
                                 "aq-strength": "8", "rc-lookahead": "0"}
            codec_ctx.open()
            self._codec = codec_ctx
            self.codec = codec
            self._av = av
            if cursor:
                try:
                    from cursor_overlay import CursorOverlay
                    self._cursor = CursorOverlay()
                except Exception:  # noqa: BLE001
                    self._cursor = None
            else:
                self._cursor = None
            sock = socket.create_connection((host, port), timeout=4)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 18)
            self._sock = sock
            self._width, self._height = width, height
            self._framed = framed
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self.running = True
            self.size = "%dx%d" % (width, height)
            self.bitrate = bitrate
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.stop()
            return False

    def _fit(self, frame):
        """Keep the previous full-screen stretch; the goggles fill 16:9."""
        return frame

    def _loop(self) -> None:
        av = self._av
        last_t = time.time()
        last_f = last_b = 0
        while not self._stop.is_set():
            try:
                frame = self._cam.get_latest_frame()
                if frame is None:
                    continue
                if self._cursor is not None:
                    try:
                        if not frame.flags.writeable:
                            frame = frame.copy()
                        self._cursor.draw(frame)
                    except Exception:  # noqa: BLE001
                        self._cursor = None
                frame = self._fit(frame)
                t0 = time.time()
                vf = av.VideoFrame.from_ndarray(frame, format="bgra")
                if (frame.shape[1], frame.shape[0]) != (self._width, self._height):
                    vf = vf.reformat(width=self._width, height=self._height,
                                     format="yuv420p")
                else:
                    vf = vf.reformat(format="yuv420p")
                pkts = list(self._codec.encode(vf))
                self.encode_ms = (self.encode_ms * 0.9 +
                                  (time.time() - t0) * 100.0)
                for pkt in pkts:
                    data = bytes(pkt)
                    if data:
                        if self._framed:
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

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._cam is not None:
            try:
                self._cam.stop()
            except Exception:  # noqa: BLE001
                pass
            self._cam = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.running = False

    def stats(self) -> dict:
        return {
            "running": self.running,
            "size": self.size,
            "bitrate": self.bitrate,
            "codec": self.codec,
            "frames": self.frames,
            "bytes": self.bytes,
            "fps": round(self.fps, 1),
            "kbps": int(self.kbps),
            "encode_ms": round(self.encode_ms, 1),
            "last_error": self.last_error,
        }
