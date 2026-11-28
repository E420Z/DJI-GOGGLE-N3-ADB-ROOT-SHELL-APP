"""PC -> goggles 1080p60 hardware tunnel backend.

This replaces the old JPEG/fb_receiver "PC Stream" route. It pushes
n3h264live.so, starts the patched UI with hook_overlay + the live module,
arms the vc8000d -> extra_blending tunnel, and runs the NVENC sender.
"""

from __future__ import annotations

import os
import threading
import time

import n3ctl
import display_mode
from h264send import H264Sender

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_ASSET = os.path.join(APP_DIR, "assets", "n3h264live.so")
HOOK_ASSET = os.path.join(APP_DIR, "assets", "hook_overlay.so")
LIVE_SO = "/vendor/n3h264live.so"
HOOK_SO = "/vendor/hook_overlay.so"
STAT = "/data/local/tmp/h264live.stat"
TRIGGERS = ("/data/local/tmp/h264live_sink",
            "/data/local/tmp/h264live_fork",
            "/data/local/tmp/h264live_hw",
            "/data/local/tmp/h264live_tunnel",
            "/data/local/tmp/h264live_uv",
            "/data/local/tmp/h264live_hevc",
            "/data/local/tmp/h264live_on")


class N3Live:
    def __init__(self, note=None):
        self._note = note or (lambda _m: None)
        self._sender = H264Sender(note=note)
        self._lock = threading.Lock()
        self._state = "idle"
        self._message = "Idle."
        self._settings = {"codec": "h264", "bitrate": 30_000_000,
                          "cursor": True, "auto_display": True,
                          "size": "1920x1080", "fps": 60}
        self._display_switched = False

    # ------------------------------------------------------------ helpers
    def _sh(self, cmd, t=25):
        try:
            return n3ctl.run_root(cmd, timeout=t, retries=1) or ""
        except Exception as exc:  # noqa: BLE001
            return "ERR %s" % exc

    def _device(self):
        text = self._sh("cat %s 2>/dev/null" % STAT, 10)
        out = {"stat": {}, "ui": "", "root": False}
        for line in (text or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                try:
                    out["stat"][k.strip()] = int(v.strip())
                except ValueError:
                    out["stat"][k.strip()] = v.strip()
        out["root"] = n3ctl.is_root()
        try:
            out["ui"] = (n3ctl.ui_state() or {}).get("pid", "")
        except Exception:  # noqa: BLE001
            out["ui"] = ""
        return out

    def _arm(self, hevc: bool, out: bool):
        uv = "echo 0 > /data/local/tmp/h264live_uv; "
        files = ["/data/local/tmp/h264live_sink",
                 "/data/local/tmp/h264live_fork",
                 "/data/local/tmp/h264live_hw"]
        if out:
            files.append("/data/local/tmp/h264live_tunnel")
        if hevc:
            files.append("/data/local/tmp/h264live_hevc")
        files.append("/data/local/tmp/h264live_on")
        return self._sh(uv + "touch " + " ".join(files) + "; echo ok", 10)

    def _cleanup_triggers(self):
        self._sh("rm -f " + " ".join(TRIGGERS) +
                 " /data/local/tmp/h264live.stat; echo ok", 10)

    def _display_info(self):
        return {
            "current": display_mode.current(),
            "saved": display_mode.saved(),
            "switched": bool(self._display_switched),
            "auto": bool(self._settings.get("auto_display", True)),
            "target": "1920x1080@60",
        }

    # ------------------------------------------------------------ api
    def info(self):
        sender = self._sender.stats()
        dev = self._device()
        stat = dev.get("stat", {})
        return {
            "ok": True,
            "state": self._state,
            "message": self._message,
            "stats": {
                "fps": sender.get("fps", 0),
                "kbps": sender.get("kbps", 0),
                "bitrate": sender.get("bitrate", self._settings["bitrate"]),
                "codec": sender.get("codec", self._settings["codec"]),
                "size": sender.get("size", self._settings["size"]),
                "frames": sender.get("frames", 0),
                "bytes": sender.get("bytes", 0),
                "encode_ms": sender.get("encode_ms", 0),
                "drops": stat.get("drop", 0),
                "device_frames": stat.get("frames", 0),
                "input_empty": stat.get("inempty", 0),
            },
            "device": dev,
            "display": self._display_info(),
            "settings": dict(self._settings),
            "notes": [
                "Hardware vc8000d decoder tunneled straight into the "
                "extra_blending video plane.",
                "Disconnect/power off the O4 air unit: it shares the display "
                "sink and can hold a D-Log M colour mode.",
                "Experimental: restore the stock UI / power-cycle to recover.",
            ],
        }

    def start(self, codec="h264", bitrate=30_000_000, cursor=True,
              auto_display=None):
        with self._lock:
            if self._sender.running:
                return {"ok": True, "message": "PC video is already running.",
                        "stats": self._sender.stats()}
            self._state = "starting"
            self._message = "Starting hardware tunnel..."
            if not n3ctl.is_root():
                self._note("starting root shell")
                n3ctl.start_root(log=self._note)
            if not n3ctl.is_root():
                self._state = "error"
                self._message = "Root shell is not available."
                return {"ok": False, "message": self._message}
            if not os.path.exists(LIVE_ASSET):
                self._state = "error"
                self._message = "Missing app/assets/n3h264live.so"
                return {"ok": False, "message": self._message}
            if not n3ctl.dev_exists("/vendor/n3mods.so"):
                self._state = "error"
                self._message = ("Mod loader (n3mods.so) is not installed. "
                                 "Install the N3 mods from Mods & UI first.")
                return {"ok": False, "message": self._message}

            self._settings.update({"codec": codec, "bitrate": int(bitrate),
                                   "cursor": bool(cursor)})
            if auto_display is not None:
                self._settings["auto_display"] = bool(auto_display)
            if self._settings.get("auto_display", True):
                sw, orig = display_mode.ensure_1080()
                self._display_switched = bool(sw)
                if sw:
                    self._note("PC display -> 1920x1080 @ 60 Hz"
                               + (" (from %dx%d)" % (orig["w"], orig["h"])
                                  if orig else ""))
            try:
                self._note("remount /vendor rw")
                self._sh("mount -o remount,rw /vendor", 20)
                self._note("push %s" % os.path.basename(LIVE_ASSET))
                n3ctl.push_file(LIVE_ASSET, LIVE_SO, log=self._note)
                if (os.path.exists(HOOK_ASSET) and
                        not n3ctl.dev_exists(HOOK_SO)):
                    self._note("push hook_overlay.so")
                    n3ctl.push_file(HOOK_ASSET, HOOK_SO, log=self._note)
                self._sh("chmod 755 %s %s" % (LIVE_SO, HOOK_SO), 10)
                self._sh("sync; mount -o remount,ro /vendor", 20)

                self._note("starting patched UI (hook_overlay + n3h264live)")
                ok = n3ctl.start_ui(log=self._note,
                                    mods=[HOOK_SO, LIVE_SO])
                if not ok:
                    self._state = "error"
                    self._message = "The patched UI did not start."
                    return {"ok": False, "message": self._message}

                self._cleanup_triggers()
                self._arm(codec == "h265", True)
                self._note("starting NVENC %s sender" % codec.upper())
                started = False
                for _ in range(12):
                    if self._sender.start(
                            "192.168.60.2", 5572, 1920, 1080, 60,
                            self._settings["bitrate"], framed=True,
                            cursor=self._settings["cursor"], codec=codec):
                        started = True
                        break
                    time.sleep(1.0)
                if not started:
                    self._stop_locked(restore=True)
                    self._state = "error"
                    self._message = ("Sender failed: %s" %
                                     (self._sender.last_error or "no route"))
                    return {"ok": False, "message": self._message}

                self._state = "live"
                self._message = "Live 1080p60 hardware tunnel."
                return {"ok": True, "message": self._message,
                        "stats": self._sender.stats()}
            except Exception as exc:  # noqa: BLE001
                self._note("pcvideo start: %s" % exc)
                self._stop_locked(restore=True)
                self._state = "error"
                self._message = "Start failed: %s" % exc
                return {"ok": False, "message": self._message}

    def _stop_locked(self, restore=True):
        self._sender.stop()
        self._cleanup_triggers()
        self._sh("for p in $(pidof n3hlive); do kill -9 $p; done; "
                 "for p in $(pidof dji_glasses_patched); do kill -9 $p; done; "
                 "echo ok", 10)
        if self._display_switched:
            m = display_mode.restore()
            if m:
                self._display_switched = False
                self._note("PC display restored to %dx%d @ %d Hz"
                           % (m["w"], m["h"], m.get("hz") or 60))
            else:
                self._note("PC display restore failed (use Restore)")
        if restore:
            try:
                n3ctl.start_stock_ui(log=self._note)
            except Exception as exc:  # noqa: BLE001
                self._note("restore UI: %s" % exc)

    def stop(self):
        with self._lock:
            self._stop_locked(restore=True)
            stats = self._sender.stats()
            self._state = "idle"
            self._message = "Stopped. Stock UI restored."
            return {"ok": True, "message": self._message, "stats": stats}

    def set_settings(self, codec=None, bitrate=None, cursor=None,
                     auto_display=None):
        with self._lock:
            if codec in ("h264", "h265"):
                self._settings["codec"] = codec
            if bitrate is not None:
                self._settings["bitrate"] = int(bitrate)
            if cursor is not None:
                self._settings["cursor"] = bool(cursor)
            if auto_display is not None:
                self._settings["auto_display"] = bool(auto_display)
            return {"ok": True,
                    "message": "Settings saved; start/restart to apply.",
                    "settings": dict(self._settings),
                    "display": self._display_info()}

    def display_control(self, switch_now=False, restore=False):
        with self._lock:
            if self._sender.running:
                return {"ok": False,
                        "message": "Stop the tunnel before changing the display.",
                        "display": self._display_info()}
            if switch_now:
                if display_mode.is_target():
                    self._note("PC display is already 1920x1080")
                else:
                    sw, orig = display_mode.ensure_1080()
                    if sw:
                        self._display_switched = True
                        self._note("PC display -> 1920x1080 @ 60 Hz")
                    else:
                        self._note("PC display switch failed")
            if restore:
                m = display_mode.restore()
                if m:
                    self._display_switched = False
                    self._note("PC display restored to %dx%d @ %d Hz"
                               % (m["w"], m["h"], m.get("hz") or 60))
                else:
                    self._note("No saved PC display mode")
            return {"ok": True, "message": "Display updated.",
                    "display": self._display_info()}

