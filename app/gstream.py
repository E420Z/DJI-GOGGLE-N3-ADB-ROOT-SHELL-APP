"""Goggles -> PC video out.

Owns the device side (deploy/arm the n3videoout mod), the TCP H.264 feed on
port 5571, an ffmpeg remux to fragmented MP4, and a loopback HTTP endpoint
that the Goggles Stream page plays with MSE.

Device writes are limited to /vendor/n3videoout.so and /data/local/tmp.
"""
from __future__ import annotations

import atexit
import glob
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)

HOST = "192.168.60.2"
TCP_PORT = 5571
HTTP_PORT = 8771
MOD_LOCAL = os.path.join(REPO_DIR, "mods", "h264", "n3videoout.so")
MOD_REMOTE = "/vendor/n3videoout.so"
MOD_NAME = "n3videoout"
MARKER = "/data/local/tmp/videoout_on"
STAT_PATH = "/data/local/tmp/videoout.stat"
STREAM_URL = "http://127.0.0.1:%d/stream.mp4" % HTTP_PORT

BOX_CAP = 512 * 1024


def find_ffmpeg() -> str:
    env = os.environ.get("FFMPEG")
    if env and os.path.exists(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        os.path.join(REPO_DIR, "tools", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for base in (os.path.expanduser(r"~\Downloads"),
                 os.path.expanduser(r"~\Desktop")):
        hits = glob.glob(os.path.join(base, "ffmpeg*", "bin", "ffmpeg.exe"))
        if hits:
            return hits[0]
    return ""


class StreamBuffer:
    """Fragmented-MP4 init segment + a bounded list of moof/mdat segments."""

    def __init__(self) -> None:
        self.lock = threading.Condition()
        self.init = b""
        self.segs: list[bytes] = []
        self.total = 0
        self.floor = 0
        self.buf = b""
        self.pending = b""
        self.closed = False

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.buf += data
            while True:
                if len(self.buf) < 8:
                    break
                size = struct.unpack(">I", self.buf[:4])[0]
                header = 8
                if size == 1:
                    if len(self.buf) < 16:
                        break
                    size = struct.unpack(">Q", self.buf[8:16])[0]
                    header = 16
                elif size == 0:
                    size = len(self.buf)
                if size < header or len(self.buf) < size:
                    break
                box = self.buf[:size]
                self.buf = self.buf[size:]
                kind = box[4:8]
                if kind in (b"ftyp", b"moov"):
                    self.init += box
                elif kind == b"moof":
                    self.pending = box
                elif kind == b"mdat":
                    if self.pending:
                        seg = self.pending + box
                        self.pending = b""
                        self.segs.append(seg)
                        self.total += len(seg)
                        while self.total > BOX_CAP and len(self.segs) > 1:
                            self.total -= len(self.segs.pop(0))
                            self.floor += 1
                        self.lock.notify_all()
                elif kind in (b"free", b"skip", b"sidx", b"styp"):
                    continue
            if len(self.buf) > BOX_CAP:
                self.buf = self.buf[-BOX_CAP:]

    def start(self, timeout: float = 8.0):
        end = time.time() + timeout
        with self.lock:
            while not (self.init and self.segs) and not self.closed:
                left = end - time.time()
                if left <= 0:
                    return None
                self.lock.wait(left)
            if self.closed:
                return None
            floor = self.floor
            return self.init, floor

    def next_seg(self, cursor: int, timeout: float = 5.0):
        end = time.time() + timeout
        with self.lock:
            while True:
                if cursor < self.floor:
                    cursor = self.floor
                idx = cursor - self.floor
                if idx < len(self.segs):
                    return self.segs[idx], cursor + 1
                if self.closed:
                    return None
                left = end - time.time()
                if left <= 0:
                    return False
                self.lock.wait(left)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.lock.notify_all()


class _Handler(BaseHTTPRequestHandler):
    server_version = "N3GStream"

    def log_message(self, *_a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] != "/stream.mp4":
            self.send_error(404)
            return
        buf = self.server.buf
        start = buf.start(8.0)
        if not start:
            self.send_error(503, "stream not ready")
            return
        init, cursor = start
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(init)
            while True:
                item = buf.next_seg(cursor, 5.0)
                if item is None:
                    break
                if item is False:
                    continue
                seg, cursor = item
                self.wfile.write(seg)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, buf):
        self.buf = buf
        super().__init__(addr, handler)


class GogglesStream:
    def __init__(self, n3ctl) -> None:
        self.n3 = n3ctl
        self.lock = threading.RLock()
        self.state = "idle"
        self.message = "Idle."
        self.ffmpeg = find_ffmpeg()
        self.error = ""
        self.buf = StreamBuffer()
        self.httpd = None
        self.sock = None
        self.proc = None
        self.threads: list[threading.Thread] = []
        self.bytes = 0
        self.frames = 0
        self.fps = 0.0
        self.kbps = 0.0
        self.dropped = 0
        self.width = 1920
        self.height = 1080
        self.device = {}
        self.last_error = ""
        self._stat_t = 0.0
        self._stop = threading.Event()
        atexit.register(self._on_exit)

    def _on_exit(self) -> None:
        try:
            self.stop()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- helpers
    def _sh(self, cmd: str, timeout: float = 20.0) -> str:
        try:
            return self.n3.run_root(cmd, timeout=timeout, retries=1) or ""
        except Exception as exc:  # noqa: BLE001
            return "ERR %s" % exc

    def _deploy(self) -> str:
        if not os.path.exists(MOD_LOCAL):
            return "missing %s" % MOD_LOCAL
        remote = self._sh("stat -c %%s %s 2>/dev/null" % MOD_REMOTE, 10).strip()
        if remote.isdigit() and int(remote) == os.path.getsize(MOD_LOCAL):
            return ""
        self._sh("mount -o remount,rw /vendor", 20)
        try:
            self.n3.push_file(MOD_LOCAL, MOD_REMOTE)
        finally:
            self._sh("sync; mount -o remount,ro /vendor", 20)
        self._sh("chmod 755 %s" % MOD_REMOTE, 10)
        return ""

    def _ensure_ui(self) -> str:
        st = self.n3.ui_state() or {}
        pid = st.get("pid")
        mapped = self._sh("grep -c %s /proc/%s/maps 2>/dev/null" % (MOD_NAME, pid), 10).strip()
        if pid and mapped and mapped != "0":
            return ""
        if not self.n3.start_ui(log=lambda _m: None,
                                mods=["/vendor/hook_overlay.so", MOD_REMOTE]):
            return "The goggles UI did not restart with the video-out mod."
        # start_ui returns after ~6 s; give the loader and mod a moment to map
        for _ in range(20):
            st = self.n3.ui_state() or {}
            pid = st.get("pid")
            if pid:
                mapped = self._sh(
                    "grep -c %s /proc/%s/maps 2>/dev/null" % (MOD_NAME, pid), 8).strip()
                if mapped and mapped != "0":
                    return ""
            time.sleep(0.5)
        return "The video-out mod did not load into the goggles UI."

    def _read_device(self) -> None:
        out = self._sh("cat %s 2>/dev/null" % STAT_PATH, 8)
        vals = dict(re.findall(r"(\w+)=(-?\d+)", out or ""))
        if vals:
            self.device = {k: int(v) for k, v in vals.items()}
            self.dropped = int(vals.get("dropped", self.dropped))

    # ------------------------------------------------------------------ start
    def start(self) -> dict:
        with self.lock:
            if self.state in ("starting", "live"):
                return {"ok": True, "message": "Already running.", "state": self.state}
            self.state = "starting"
            self.message = "Starting video out..."
            self.error = ""
            self.bytes = self.frames = 0
            self.fps = self.kbps = 0.0
            self.dropped = 0
            self.buf = StreamBuffer()
            if self.httpd is not None:
                self.httpd.buf = self.buf

        try:
            if not self.ffmpeg:
                raise RuntimeError(
                    "ffmpeg was not found. Install it (winget install ffmpeg) "
                    "or set FFMPEG=C:\\path\\to\\ffmpeg.exe.")

            if not self.n3.is_root() and not self.n3.start_root(log=lambda _m: None):
                raise RuntimeError("Start the root shell first (Connection page).")

            err = self._deploy()
            if err:
                raise RuntimeError(err)
            err = self._ensure_ui()
            if err:
                raise RuntimeError(err)

            self._sh("rm -f %s" % MARKER, 10)
            self._sh("setprop test.applv.enable 1; setprop test.applv.func.on 1", 10)
            time.sleep(0.8)
            self._sh("touch %s" % MARKER, 10)

            sock = None
            for _ in range(60):
                try:
                    sock = socket.create_connection((HOST, TCP_PORT), timeout=2)
                    break
                except OSError:
                    time.sleep(0.5)
            if sock is None:
                raise RuntimeError("No listener on %s:%d (mod did not arm)." % (HOST, TCP_PORT))
            self.sock = sock
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

            self._start_http()
            self._start_ffmpeg()

            self._stop.clear()
            for fn in (self._tcp_loop, self._mp4_loop, self._log_loop):
                t = threading.Thread(target=fn, daemon=True)
                t.start()
                self.threads.append(t)

            self.state = "live"
            self.message = "Live: 1080p60 H.264 over USB."
            self.last_error = ""
            return {"ok": True, "message": self.message, "state": self.state,
                    "stream_url": STREAM_URL}
        except Exception as exc:  # noqa: BLE001
            self._cleanup()
            self.state = "error"
            self.message = str(exc)
            return {"ok": False, "message": self.message, "state": self.state}

    # ------------------------------------------------------------------- stop
    def stop(self) -> dict:
        with self.lock:
            if self.state == "idle":
                return {"ok": True, "message": "Already idle."}
            self.state = "idle"
            self.message = "Stopped."
        self._cleanup()
        return {"ok": True, "message": "Stopped.", "stats": self._stats()}

    def _cleanup(self) -> None:
        self._stop.set()
        try:
            self._sh("rm -f %s" % MARKER, 10)
            self._sh("setprop test.applv.func.on 0; setprop test.applv.enable 0", 10)
        except Exception:  # noqa: BLE001
            pass
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None
        for t in self.threads:
            if t is not threading.current_thread():
                t.join(timeout=0.4)
        self.threads = []
        self.buf.close()
        self.fps = self.kbps = 0.0
        self.device = {}

    # ------------------------------------------------------------------- http
    def _start_http(self) -> None:
        if self.httpd is not None:
            return
        srv = _Server(("127.0.0.1", HTTP_PORT), _Handler, self.buf)
        self.httpd = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    # ----------------------------------------------------------------- ffmpeg
    def _start_ffmpeg(self) -> None:
        cmd = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-probesize", "32", "-analyzeduration", "0",
            "-framerate", "60", "-f", "h264", "-i", "pipe:0",
            "-c", "copy",
            "-movflags", "+frag_every_frame+empty_moov+default_base_moof",
            "-flush_packets", "1",
            "-f", "mp4", "pipe:1",
        ]
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, creationflags=flags)

    # ----------------------------------------------------------------- reader
    def _tcp_loop(self) -> None:
        carry = b""
        last_t = time.time()
        last_bytes = last_frames = 0
        buf = bytearray(262144)
        while not self._stop.is_set():
            try:
                n = self.sock.recv_into(buf)
            except OSError as exc:
                if not self._stop.is_set():
                    self._fail("Stream stopped: %s" % exc)
                return
            if not n:
                if not self._stop.is_set():
                    self._fail("The goggles closed the stream.")
                return
            chunk = bytes(buf[:n])
            self.bytes += n
            probe = carry + chunk
            self.frames += probe.count(b"\x00\x00\x01\x09")
            carry = probe[-3:]
            proc = self.proc
            if proc is not None and proc.stdin is not None:
                try:
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    if not self._stop.is_set():
                        self._fail("ffmpeg stopped (encoder pipe closed).")
                    return
            now = time.time()
            if now - last_t >= 1.0:
                dt = now - last_t
                self.fps = (self.frames - last_frames) / dt
                self.kbps = (self.bytes - last_bytes) * 8.0 / 1000.0 / dt
                last_t, last_bytes, last_frames = now, self.bytes, self.frames
                if now - self._stat_t >= 2.0:
                    self._stat_t = now
                    self._read_device()

    def _mp4_loop(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        while not self._stop.is_set():
            data = proc.stdout.read(65536)
            if not data:
                if not self._stop.is_set():
                    self._fail("ffmpeg exited; no MP4 output.")
                return
            self.buf.feed(data)

    def _log_loop(self) -> None:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        for line in iter(proc.stderr.readline, b""):
            text = line.decode("utf-8", "replace").strip()
            if text:
                self.last_error = text[-400:]

    def _fail(self, message: str) -> None:
        with self.lock:
            if self.state != "live":
                return
            self.state = "error"
            self.message = message
        self._cleanup()

    # ------------------------------------------------------------------- info
    def _stats(self) -> dict:
        return {
            "fps": round(self.fps, 1),
            "kbps": int(self.kbps),
            "frames": self.frames,
            "dropped": self.dropped,
            "width": self.width,
            "height": self.height,
            "latency_ms": 0,
            "bytes": self.bytes,
        }

    def info(self) -> dict:
        if self.state == "live" and time.time() - self._stat_t > 2.5:
            self._stat_t = time.time()
            self._read_device()
        dev = {
            "mod": bool(self.device),
            "fills": self.device.get("frames", 0),
            "sent": self.device.get("sent", 0),
            "drops": self.device.get("dropped", 0),
            "props": self.state == "live",
        }
        return {
            "ok": self.state != "error",
            "state": self.state,
            "message": self.message,
            "stream_url": STREAM_URL if self.state == "live" else "",
            "stats": self._stats(),
            "device": dev,
            "ffmpeg": {"available": bool(self.ffmpeg), "path": self.ffmpeg},
        }
