"""Live preview + screenshot support for the N3 ROOT app."""
from __future__ import annotations

import datetime
import os
import struct
import subprocess
import sys
import threading
import time

from PIL import Image

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import n3ctl  # noqa: E402

LIVE_LOCAL = os.path.join(APP_DIR, "plugins", "n3live", "files", "n3live.so")
CAP_LOCAL = os.path.join(APP_DIR, "plugins", "capture", "files", "hook_capture.so")
LIVE_REMOTE = "/vendor/n3live.so"
CAP_REMOTE = "/vendor/hook_capture.so"
FIFO = "/data/local/tmp/n3live.fifo"
HDR = struct.Struct("<4sHHI")


def _read_exact(f, n: int):
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def hook_loaded(name: str = "hook_capture") -> bool:
    st = n3ctl.ui_state()
    pid = st.get("pid") or ""
    if not pid:
        return False
    out = n3ctl.run_root(
        "grep -q %s /proc/%s/maps && echo yes || echo no" % (name, pid),
        timeout=8, retries=1)
    return out.strip().endswith("yes")


class LiveStream:
    """Reads the n3live FIFO and delivers PIL frames."""

    def __init__(self, log, on_frame, on_status):
        self.log = log
        self.on_frame = on_frame
        self.on_status = on_status
        self.proc = None
        self.thread = None
        self.stop_evt = threading.Event()
        self.running = False
        self.record = False
        self.rec_frames = []
        self.last_size = (0, 0)

    def start(self, app_mods=None):
        app_mods = [m for m in (app_mods or []) if m]
        if self.running:
            return
        self.log("Preparing live preview…")
        n3ctl.ensure_adb(log=self.log)
        with n3ctl.vendor_write(log=self.log):
            n3ctl.push_file(LIVE_LOCAL, LIVE_REMOTE, log=self.log)
            n3ctl.push_file(CAP_LOCAL, CAP_REMOTE, log=self.log)
            n3ctl.run_root("chmod 644 %s %s" % (LIVE_REMOTE, CAP_REMOTE),
                           timeout=8, retries=1)

        mods = [LIVE_REMOTE, CAP_REMOTE] + app_mods
        self.log("Restarting the goggles UI with live+capture…")
        if not n3ctl.start_ui(log=self.log, mods=mods):
            raise RuntimeError("UI did not restart")
        time.sleep(3.0)

        n3ctl.ensure_adb(log=self.log)
        if not n3ctl.is_root():
            n3ctl.start_root(log=self.log)
        n3ctl.run_root("rm -f %s; mkfifo %s; chmod 666 %s"
                       % (FIFO, FIFO, FIFO), timeout=8, retries=1)

        adb = n3ctl.find_adb()
        self.proc = subprocess.Popen([adb, "exec-out", "cat", FIFO],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0)
        self.stop_evt.clear()
        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        self.log("Live preview started (160x90, ~57 fps).")

    def _reader(self):
        count = 0
        t0 = time.time()
        out = self.proc.stdout if self.proc else None
        while not self.stop_evt.is_set() and out is not None:
            hdr = _read_exact(out, HDR.size)
            if hdr is None:
                break
            magic, w, h, seq = HDR.unpack(hdr)
            if magic != b"N3LV" or not w or not h or w > 1920 or h > 1080:
                continue
            data = _read_exact(out, w * h * 4)
            if data is None:
                break
            try:
                img = Image.frombytes("RGB", (w, h), data, "raw", "BGRX")
            except Exception:
                continue
            self.last_size = (w, h)
            count += 1
            if self.record:
                self.rec_frames.append(img)
                if len(self.rec_frames) > 900:
                    self.record = False
            try:
                self.on_frame(img)
            except Exception:
                pass
            now = time.time()
            if now - t0 >= 1.0:
                try:
                    self.on_status(count / (now - t0), (w, h))
                except Exception:
                    pass
                count = 0
                t0 = now

    def begin_record(self):
        self.rec_frames = []
        self.record = True

    def end_record(self, path: str):
        self.record = False
        frames = list(self.rec_frames)
        self.rec_frames = []
        if not frames:
            raise RuntimeError("no frames recorded")
        if len(frames) > 600:
            frames = frames[:: max(1, len(frames) // 600)]
        dur = max(20, int(1000 / 57))
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=dur, loop=0, format="GIF")
        return path, len(frames)

    def stop(self):
        self.stop_evt.set()
        self.record = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
        try:
            if n3ctl.is_root():
                n3ctl.run_root("rm -f %s /data/local/tmp/n3_app_on" % FIFO,
                               timeout=6, retries=1)
        except Exception:
            pass
        try:
            n3ctl.restore_stock(log=self.log)
        except Exception as exc:
            self.log("USB restore warning: %s" % exc)
        try:
            n3ctl.stop_root(log=self.log)
        except Exception:
            pass
        self.running = False
        self.on_status(0.0, (0, 0))
        self.log("Live preview stopped.")


def capture_png(app_mods, outdir: str, log=print) -> str:
    """Trigger the safe capture hook and save one PNG."""
    app_mods = [m for m in (app_mods or []) if m]
    os.makedirs(outdir, exist_ok=True)
    n3ctl.ensure_adb(log=log)
    if not n3ctl.is_root() and not n3ctl.start_root(log=log):
        raise RuntimeError("root shell unavailable")

    if not n3ctl.dev_exists(CAP_REMOTE):
        with n3ctl.vendor_write(log=log):
            n3ctl.push_file(CAP_LOCAL, CAP_REMOTE, log=log)
            n3ctl.run_root("chmod 644 %s" % CAP_REMOTE, timeout=6, retries=1)

    if not hook_loaded("hook_capture"):
        log("Loading the capture hook (UI restart)…")
        if not n3ctl.start_ui(log=log, mods=[CAP_REMOTE] + app_mods):
            raise RuntimeError("UI did not restart with capture hook")
        time.sleep(3.0)
        n3ctl.ensure_adb(log=log)
        if not n3ctl.is_root():
            n3ctl.start_root(log=log)

    n3ctl.run_root(
        "rm -f /data/local/tmp/screencap0.bin /data/local/tmp/screencap1.bin "
        "/data/local/tmp/screencap.done; touch /data/local/tmp/n3_capture",
        timeout=8, retries=1)
    ok = False
    for _ in range(20):
        time.sleep(1)
        out = n3ctl.run_root(
            "test -f /data/local/tmp/screencap.done && echo yes || echo no",
            timeout=6, retries=1)
        if out.strip().endswith("yes"):
            ok = True
            break
    n3ctl.run_root("rm -f /data/local/tmp/n3_capture", timeout=6, retries=1)
    if not ok:
        raise RuntimeError("capture timed out")

    n3ctl.ensure_adb(log=log)
    adb = n3ctl.find_adb()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    png = os.path.join(outdir, "shot_%s.png" % stamp)
    for i in range(2):
        remote = "/data/local/tmp/screencap%d.bin" % i
        local = os.path.join(outdir, "slot%d.bin" % i)
        subprocess.run([adb, "pull", remote, local],
                       capture_output=True, text=True, timeout=120)
        if not os.path.exists(local):
            continue
        data = open(local, "rb").read()
        try:
            os.remove(local)
        except OSError:
            pass
        if len(data) < 1920 * 1080 * 4:
            continue
        img = Image.frombytes("RGB", (1920, 1080), data[:1920 * 1080 * 4],
                              "raw", "BGRX")
        img.save(png)
        return png
    raise RuntimeError("no dmabuf frame pulled")
