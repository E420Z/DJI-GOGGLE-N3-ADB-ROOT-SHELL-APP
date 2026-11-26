"""N3 ROOT web UI host.

Python backend for the HTML/CSS/JS control deck.  The UI is a pywebview
window; all device access stays in this file and the existing n3ctl/mods
modules.  Static UI files live in app/web/ and never talk to the goggles
directly.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import webview  # noqa: E402

import n3ctl  # noqa: E402
import mods as modman  # noqa: E402
import background  # noqa: E402
import theme_builder  # noqa: E402
from ui.live import LiveStream, capture_png, SCALE_BY_LABEL  # noqa: E402

VERSION = "1.0"
PREFS = os.path.join(APP_DIR, "state", "web_prefs.json")
SHOTS = os.path.join(APP_DIR, "state", "screenshots")


def _clip(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[-limit:]


def _ok(message: str = "Done", **extra) -> dict:
    out = {"ok": True, "message": message}
    out.update(extra)
    return out


def _fail(message: str, **extra) -> dict:
    out = {"ok": False, "message": message}
    out.update(extra)
    return out


class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self._live = None
        self._frame = ""
        self._frame_w = 0
        self._frame_h = 0
        self._frame_t = 0.0
        self._fps = 0.0
        self._frames = 0
        self._fps_t0 = time.time()
        self._log = []
        self._status_cache = None

    # ---------------------------------------------------------------- helper
    def _note(self, message: str) -> None:
        line = "[web] %s" % message
        with self._lock:
            self._log.append(line)
            self._log = self._log[-200:]
        print(line, flush=True)

    def _action(self, label: str, fn) -> dict:
        try:
            result = fn()
            if result is False:
                return _fail("%s failed; check the logs." % label)
            return _ok("%s complete." % label)
        except Exception as exc:  # noqa: BLE001
            self._note("%s: %s" % (label, exc))
            return _fail("%s: %s" % (label, exc))

    # ---------------------------------------------------------------- status
    def status(self) -> dict:
        # Both probes take 1-2 s (libusb scan, adb query), so run them together
        # and keep the answer for a couple of seconds.  The UI polls every 5 s.
        now = time.time()
        with self._lock:
            cached = self._status_cache
            if cached and now - cached[0] < 2.0:
                return dict(cached[1])
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as pool:
                st_f = pool.submit(n3ctl.status)
                ui_f = pool.submit(n3ctl.ui_state)
                st, ui = st_f.result(), ui_f.result()
        except Exception as exc:  # noqa: BLE001
            self._note("status: %s" % exc)
            st, ui = {}, {}
        adb = st.get("adb") or []
        patched = bool(ui.get("patched"))
        pid = str(ui.get("pid") or "")
        theme = "purple" if ui.get("theme") else "stock"
        try:
            menu = bool(modman.find("n3menuinject") and
                        modman.find("n3menuinject").get("installed"))
        except Exception:
            menu = False
        out = {
            "version": VERSION,
            "ui": bool(patched or pid),
            "patched": patched,
            "root": bool(st.get("root")),
            "adb": bool(adb),
            "usb": bool(st.get("usb")),
            "theme": theme,
            "background": bool(ui.get("background")),
            "menu": menu,
            "pid": pid,
            "transport": "ADB + root" if adb and st.get("root") else
                         "ADB" if adb else
                         "USB" if st.get("usb") else "offline",
            "serial": "••••••••",
            "device": "DJI Goggles N3",
        }
        with self._lock:
            self._status_cache = (time.time(), dict(out))
        return out

    # --------------------------------------------------------------- actions
    def enable_adb(self) -> dict:
        return self._action("Enable ADB",
                            lambda: n3ctl.enable_adb(log=self._note))

    def start_root(self) -> dict:
        return self._action("Start root",
                            lambda: n3ctl.start_root(log=self._note))

    def stop_root(self) -> dict:
        return self._action("Stop root",
                            lambda: n3ctl.stop_root(log=self._note))

    def start_ui(self) -> dict:
        return self._action(
            "Start patched UI",
            lambda: n3ctl.start_ui(log=self._note,
                                   mods=modman.mods_for_ui()))

    def recover_stock(self) -> dict:
        return self._action("Recover stock UI",
                            lambda: n3ctl.start_stock_ui(log=self._note))

    def open_terminal(self) -> dict:
        try:
            n3ctl.open_terminal()
            return _ok("Opened a root terminal.")
        except Exception as exc:  # noqa: BLE001
            return _fail("Terminal: %s" % exc)

    # ------------------------------------------------------------------ docs
    _DOC_ROOT = os.path.dirname(APP_DIR)

    def open_doc(self, path: str) -> dict:
        """Open a file under docs/ in the desktop's default application.

        Read-only: the file is handed to the OS, never modified.
        """
        rel = (path or "").replace("\\", "/").strip()
        if not rel.startswith("docs/") or ".." in rel:
            return _fail("Only files under docs/ can be opened.")
        root = os.path.abspath(self._DOC_ROOT)
        full = os.path.abspath(os.path.join(root, rel))
        if not full.startswith(root + os.sep):
            return _fail("Refusing to open %s" % rel)
        if not os.path.isfile(full):
            return _fail("Missing file: %s" % rel)
        try:
            if hasattr(os, "startfile"):
                os.startfile(full)  # noqa: S606 - user-requested local doc
            else:
                import subprocess
                subprocess.Popen(["xdg-open", full])
            return _ok("Opened %s." % rel)
        except Exception as exc:  # noqa: BLE001
            return _fail("Could not open %s: %s" % (rel, exc))

    # ------------------------------------------------------------- root shell
    # Hard block: the app must never write /system or touch verity/partitions.
    _SHELL_BLOCK = (
        "/system", "verity", "avb", "fastboot", "rpmb", "otp", "fuse",
        "mkfs", "bootloader", "flash ", "flash_", "dd if=", "dd of=",
        "remount,rw", "setprop.*verity", "setprop.*selinux",
    )

    def run_shell(self, command: str) -> dict:
        cmd = (command or "").strip()
        if not cmd:
            return _fail("Empty command.")
        low = cmd.lower()
        import re
        for bad in self._SHELL_BLOCK:
            if bad in low or re.search(bad, low):
                return _fail("Blocked: this shell will not touch /system, "
                             "verity, partitions or bootloader.")
        try:
            if not n3ctl.is_root():
                return _fail("Start the root shell first.")
            out = n3ctl.run_root(cmd, timeout=30, retries=1)
            return _ok("Command complete.", output=_clip(out, 8000))
        except Exception as exc:  # noqa: BLE001
            return _fail("Shell: %s" % exc)

    # ------------------------------------------------------------------ mods
    def mods_list(self) -> dict:
        try:
            rows = []
            for m in modman.refresh():
                rows.append({
                    "id": m.get("id", ""),
                    "name": m.get("name", m.get("id", "")),
                    "version": m.get("version", ""),
                    "type": m.get("type", ""),
                    "risk": m.get("risk", "medium"),
                    "installed": bool(m.get("installed")),
                    "experimental": bool(m.get("experimental")),
                    "description": m.get("description", ""),
                    "notes": m.get("notes", ""),
                })
            return {"mods": rows}
        except Exception as exc:  # noqa: BLE001
            return {"mods": [], "error": str(exc)}

    def install_mod(self, mod_id: str) -> dict:
        return self._action("Install %s" % mod_id,
                            lambda: modman.install(mod_id, log=self._note))

    def uninstall_mod(self, mod_id: str) -> dict:
        return self._action("Uninstall %s" % mod_id,
                            lambda: modman.uninstall(mod_id, log=self._note))

    # ---------------------------------------------------------------- themes
    def themes(self) -> dict:
        return {"themes": list(theme_builder.PRESETS.keys())}

    def apply_theme(self, name: str) -> dict:
        def build():
            if name not in theme_builder.PRESETS:
                raise RuntimeError("unknown theme: %s" % name)
            stock = theme_builder.find_stock_lib(APP_DIR)
            if not stock or not os.path.exists(stock):
                raise RuntimeError("stock libew_gls.so is missing")
            out = os.path.join(APP_DIR, "state", "build",
                               "libew_gls_%s.so" %
                               name.replace(" ", "_").lower())
            os.makedirs(os.path.dirname(out), exist_ok=True)
            theme_builder.build(theme_builder.PRESETS[name],
                                theme_builder.PRESET_ENABLED[name],
                                stock, out, log=self._note)
            return n3ctl.install_theme(out, log=self._note,
                                       mods=modman.mods_for_ui())
        return self._action("Apply %s theme" % name, build)

    # ------------------------------------------------------------------ logs
    def _tail(self, path: str, lines: int = 120) -> str:
        try:
            if n3ctl.is_root():
                return n3ctl.run_root("tail -n %d %s 2>/dev/null"
                                      % (lines, path), timeout=8, retries=1)
            adb = n3ctl.find_adb()
            if adb:
                return n3ctl.adb_shell("tail -n %d %s 2>/dev/null"
                                       % (lines, path), adb=adb, timeout=8)
        except Exception:
            pass
        return ""

    def logs(self) -> dict:
        return {
            "natartos": _clip(self._tail("/data/local/tmp/natartos.log")),
            "n3mods": _clip(self._tail("/data/local/tmp/n3mods.log")),
            "ui": _clip(self._tail("/data/local/tmp/dji_glasses.log")),
            "capture": _clip(self._tail("/data/local/tmp/screencap.log")),
            "web": _clip("\n".join(self._log[-120:])),
        }

    # ------------------------------------------------------------------ live
    def _on_frame(self, image) -> None:
        try:
            now = time.time()
            if now - self._frame_t < 0.08:      # ~12 fps max
                return
            self._frame_t = now
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=72)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            with self._lock:
                self._frame = "data:image/jpeg;base64," + b64
                self._frame_w, self._frame_h = image.size
                self._frames += 1
                if now - self._fps_t0 >= 1.0:
                    self._fps = self._frames / (now - self._fps_t0)
                    self._frames = 0
                    self._fps_t0 = now
        except Exception:
            pass

    def _on_live_status(self, text: str) -> None:
        self._note("live: %s" % text)

    def live_start(self, scale_label: str = "640x360") -> dict:
        def work():
            if self._live and self._live.running:
                return True
            scale = SCALE_BY_LABEL.get(scale_label, 3)
            self._live = LiveStream(self._note, self._on_frame,
                                    self._on_live_status)
            self._live.start(app_mods=modman.mods_for_ui(), scale=scale)
            return True
        return self._action("Start live preview", work)

    def live_resolutions(self) -> dict:
        from ui.live import RESOLUTIONS
        return {
            "resolutions": [label for label, _scale in RESOLUTIONS],
            "default": "640x360",
        }

    def live_stop(self) -> dict:
        def work():
            if self._live:
                self._live.stop()
            with self._lock:
                self._frame = ""
                self._fps = 0
            return True
        return self._action("Stop live preview", work)

    def live_frame(self) -> dict:
        with self._lock:
            return {
                "ok": bool(self._frame),
                "image": self._frame,
                "width": self._frame_w,
                "height": self._frame_h,
                "fps": round(self._fps, 1),
            }

    def capture_screen(self) -> dict:
        def work():
            os.makedirs(SHOTS, exist_ok=True)
            path = capture_png(modman.mods_for_ui(), SHOTS, log=self._note)
            data = base64.b64encode(open(path, "rb").read()).decode("ascii")
            return {"path": path, "image": "data:image/png;base64," + data}
        try:
            res = work()
            return _ok("Screenshot saved.", **res)
        except Exception as exc:  # noqa: BLE001
            return _fail("Screenshot: %s" % exc)

    # -------------------------------------------------------------- sparrow2
    def sparrow_tools(self) -> dict:
        cmd = ("ls -l /system/bin/sdr_shell "
               "/system/bin/test_sparrow2_link.sh "
               "/system/bin/test_sparrow2_tsync.sh "
               "/system/bin/test_sparrow2_hw_ver.sh "
               "/system/bin/test_reset_s2_link.sh "
               "/system/bin/test_sdrlog_e3t_uart5_link.sh "
               "/system/bin/test_rf.sh 2>/dev/null")
        try:
            text = (n3ctl.run_root(cmd, timeout=12, retries=1)
                    if n3ctl.is_root() else
                    n3ctl.adb_shell(cmd, timeout=12))
            return _ok("S2 tool inventory.", text=text)
        except Exception as exc:  # noqa: BLE001
            return _fail("S2 tools: %s" % exc)

    def sparrow_console(self) -> dict:
        # Read-only vendor console help.  This is the only S2 command the web
        # UI runs; it does not start/stop or route video.
        cmd = ("timeout 12 /system/bin/sdr_shell help 2>&1; "
               "echo '---'; dji_mb_ctrl -S test -R diag -m 2304 -o 3000000 "
               "-g 14 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1 | tail -6")
        try:
            text = (n3ctl.run_root(cmd, timeout=25, retries=1)
                    if n3ctl.is_root() else
                    n3ctl.adb_shell(cmd, timeout=25))
            return _ok("S2 read-only console help.", text=text)
        except Exception as exc:  # noqa: BLE001
            return _fail("S2 console: %s" % exc)

    def sparrow_report(self) -> dict:
        try:
            st = self.status()
            return _ok("Read-only Sparrow2 summary.",
                       data={
                           "status": st,
                           "docs": ["docs/SPARROW2.md",
                                    "docs/SPARROW2-EVIDENCE.md"],
                           "note": "S2 has no AP-side IQ/ADC channel; "
                                   "capture is via the vendor USB vdec only.",
                       })
        except Exception as exc:  # noqa: BLE001
            return _fail("S2 report: %s" % exc)

    # ------------------------------------------------------------- prefs/exit
    def prefs(self) -> dict:
        try:
            with open(PREFS, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data.setdefault("accent", "purple")
        data.setdefault("motion", True)
        data.setdefault("density", "comfortable")
        data.setdefault("live_scale", "640x360")
        return data

    def set_pref(self, key: str, value) -> dict:
        data = self.prefs()
        data[key] = value
        try:
            os.makedirs(os.path.dirname(PREFS), exist_ok=True)
            with open(PREFS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return _ok("Preference saved.")
        except Exception as exc:  # noqa: BLE001
            return _fail("Preference: %s" % exc)

    def quit(self) -> dict:
        try:
            if self._live:
                self._live.stop()
        except Exception:
            pass
        for w in webview.windows:
            try:
                w.destroy()
            except Exception:
                pass
        return _ok("Closing.")


_SELFTEST_JS = r"""
(function () {
  const text = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.textContent.replace(/\s+/g, " ").trim() : null;
  };
  const active = document.querySelector(".page.is-active");
  return JSON.stringify({
    mode: document.body.dataset.mode || null,
    activePage: active ? active.id : null,
    navItems: document.querySelectorAll(".nav-item").length,
    usb: text("#stat-usb [data-field=value]"),
    root: text("#stat-root [data-field=value]"),
    adb: text("#stat-adb [data-field=value]"),
    usbCard: text("#stat-usb"),
    deviceCard: text(".device-summary, #devVersion"),
    scales: Array.from(document.querySelectorAll("#scaleGrid .scale-opt")).map((b) => b.dataset.scale),
    selectedScale: (document.getElementById("scaleSelect") || {}).value || null,
    themes: Array.from(document.querySelectorAll("#themeList .theme-opt")).map((b) => b.dataset.theme),
    hostApi: Boolean(window.pywebview && window.pywebview.api),
    errors: window.__n3errors || [],
  });
})()
"""


_SELFTEST_SETTINGS_JS = r"""
(function () {
  go("settings");
  openPalette();
  const items = document.querySelectorAll("#paletteList .palette-item");
  return JSON.stringify({
    page: (document.querySelector(".page.is-active") || {}).id || null,
    scaleOptions: document.getElementById("scaleSelect").options.length,
    themeOptions: document.querySelectorAll("#themeList .theme-opt").length,
    accentSelected: (document.querySelector('#accentGroup [aria-checked="true"]') || {}).dataset?.accent || null,
    paletteOpen: !document.getElementById("paletteOverlay").hidden,
    paletteItems: items.length,
    paletteFirst: items.length ? items[0].textContent.replace(/\s+/g, " ").trim() : null,
    errors: window.__n3errors || [],
  });
})()
"""


def _selftest(window) -> None:
    """Open the UI, let it boot, dump what it actually rendered, then close."""
    time.sleep(11)
    try:
        print("SELFTEST " + str(window.evaluate_js(_SELFTEST_JS)), flush=True)
        window.evaluate_js("go('settings')")
        time.sleep(2.5)
        print("SELFTEST2 " + str(window.evaluate_js(_SELFTEST_SETTINGS_JS)), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("SELFTEST FAILED: %s" % exc, flush=True)
    finally:
        try:
            window.destroy()
        except Exception:
            pass


def main() -> int:
    api = Api()
    index = os.path.join(APP_DIR, "web", "index.html")
    if not os.path.exists(index):
        print("missing UI:", index)
        return 1
    selftest = "--selftest" in sys.argv
    window = webview.create_window(
        "N3 ROOT — DJI Goggles N3",
        url=index,
        js_api=api,
        width=1360,
        height=880,
        min_size=(1120, 720),
        background_color="#0B0710",
        text_select=True,
    )
    webview.start(_selftest if selftest else None, window,
                  http_server=True, debug="--debug" in sys.argv,
                  private_mode=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
