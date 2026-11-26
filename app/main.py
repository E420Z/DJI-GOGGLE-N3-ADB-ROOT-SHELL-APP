"""N3 ROOT — modern control deck for DJI Goggles N3.

Pages: Connection, E42OZ (goggles/live debug), Sparrow2 (5.8 GHz radio),
Root Shell, Mods & UI, Logs, Settings. Reuses the proven n3ctl / mods /
background / theme_builder modules.
"""
from __future__ import annotations

import datetime
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import n3ctl  # noqa: E402
import mods as modman  # noqa: E402
import background  # noqa: E402
import theme_builder  # noqa: E402
from ui import theme  # noqa: E402
from ui.live import (LiveStream, capture_png, RESOLUTIONS,
                     SCALE_BY_LABEL)  # noqa: E402
from tools import probe_n3_bulk_console as bulkmod  # noqa: E402

STOCK_LIB = os.path.join(APP_DIR, "assets", "libew_gls_stock.so")
SHOTS = os.path.join(APP_DIR, "state", "shots")
VERSION = "1.0.0"


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=theme.CARD, corner_radius=14,
                        border_width=1, border_color=theme.BORDER, **kw)


def lbl(parent, text, size=13, bold=False, color=theme.TEXT, **kw):
    return ctk.CTkLabel(parent, text=text, font=theme.font(size, bold),
                        text_color=color, **kw)


def muted(parent, text, size=12, **kw):
    return ctk.CTkLabel(parent, text=text, font=theme.font(size),
                        text_color=theme.MUTED, **kw)


def pill(parent, text):
    return ctk.CTkLabel(parent, text=text, font=theme.font(11, True),
                        fg_color=theme.CARD_ALT, text_color=theme.MUTED,
                        corner_radius=8, padx=10, height=26)


def set_pill(p, on, on_text, off_text):
    p.configure(text=on_text if on else off_text,
                fg_color=theme.OK if on else theme.CARD_ALT,
                text_color="#06110A" if on else theme.MUTED)


def btn(parent, text, command, accent=False, **kw):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=theme.ACCENT if accent else theme.CARD_ALT,
        hover_color=theme.ACCENT_HOVER if accent else theme.CARD_HOVER,
        text_color="#0B0710" if accent else theme.TEXT,
        font=theme.font(13, True if accent else False),
        corner_radius=10, height=36, **kw)


class ConnectionPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        for c in range(3):
            self.grid_columnconfigure(c, weight=1)
        self.cards = {}
        specs = [("usb", "USB DEVICE", "libusb0 dji_blackbox"),
                 ("root", "ROOT SHELL", "port 4444 / uid 0"),
                 ("adb", "ADB", "USB composition")]
        for i, (key, title, sub) in enumerate(specs):
            c = card(self)
            c.grid(row=0, column=i, padx=7, pady=7, sticky="nsew")
            lbl(c, title, 11, True, theme.MUTED).pack(anchor="w", padx=16, pady=(14, 0))
            big = lbl(c, "—", 24, True, theme.MUTED)
            big.pack(anchor="w", padx=16)
            muted(c, sub).pack(anchor="w", padx=16, pady=(0, 14))
            self.cards[key] = big

        dev = card(self)
        dev.grid(row=1, column=0, columnspan=2, padx=7, pady=7, sticky="nsew")
        lbl(dev, "Goggles", 15, True).pack(anchor="w", padx=18, pady=(14, 6))
        self.info = {}
        for key, name in [("model", "Model"), ("usb", "USB"),
                          ("adb", "ADB serial"), ("ui", "UI"),
                          ("theme", "Theme"), ("background", "Background"),
                          ("mods", "Mods")]:
            row = ctk.CTkFrame(dev, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=2)
            muted(row, name, 12).pack(side="left")
            v = lbl(row, "—", 12, True)
            v.pack(side="right")
            self.info[key] = v
        ctk.CTkLabel(dev, text="", height=6).pack()

        act = card(self)
        act.grid(row=1, column=2, padx=7, pady=7, sticky="nsew")
        lbl(act, "Actions", 15, True).pack(anchor="w", padx=18, pady=(14, 8))
        grid = ctk.CTkFrame(act, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 12))
        grid.grid_columnconfigure((0, 1), weight=1)
        actions = [
            ("Enable ADB", self.act_adb, True),
            ("Start root", self.act_start_root, True),
            ("Open root console", lambda: self.app.show_page("shell"), True),
            ("Stop root", self.act_stop_root, False),
            ("Recover stock UI", self.act_stock, False),
            ("Restart patched UI", self.act_restart, False),
            ("External terminal", self.act_terminal, False),
        ]
        for i, (text, cmd, acc) in enumerate(actions):
            b = btn(grid, text, cmd, accent=acc)
            b.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew")

        helpc = card(self)
        helpc.grid(row=2, column=0, columnspan=3, padx=7, pady=7, sticky="ew")
        lbl(helpc, "First run", 15, True).pack(anchor="w", padx=18, pady=(14, 4))
        muted(helpc,
              "1) Connect USB and power on the goggles.  2) Start root (blackbox RCE).  "
              "3) Enable ADB.  4) Open E42OZ for live preview and mods.\n"
              "Recover stock UI is always available if the screen ever goes black.",
              12, justify="left").pack(anchor="w", padx=18, pady=(0, 6))
        lbl(helpc, "⚠ Experimental: custom menu/overlay and display hooks can break "
                   "rendering. See docs/EXPERIMENTAL.md. Use Recover stock UI if needed.",
            11, True, theme.WARN, wraplength=900, justify="left").pack(
                anchor="w", padx=18, pady=(0, 14))

    def act_adb(self):
        self.app.run_task(lambda: n3ctl.enable_adb(log=self.app.log),
                          "Enable ADB", on_done=lambda *_: self.app.refresh_status())

    def act_start_root(self):
        self.app.run_task(lambda: n3ctl.start_root(log=self.app.log),
                          "Start root shell", on_done=lambda *_: self.app.refresh_status())

    def act_stop_root(self):
        self.app.run_task(lambda: n3ctl.stop_root(log=self.app.log),
                          "Stop root shell", on_done=lambda *_: self.app.refresh_status())

    def act_stock(self):
        self.app.run_task(lambda: n3ctl.start_stock_ui(log=self.app.log),
                          "Recover stock UI", on_done=lambda *_: self.app.refresh_status())

    def act_restart(self):
        self.app.run_task(
            lambda: n3ctl.start_ui(log=self.app.log, mods=modman.mods_for_ui()),
            "Restart patched UI", on_done=lambda *_: self.app.refresh_status())

    def act_terminal(self):
        try:
            n3ctl.open_terminal()
            self.app.log("Opened an external root terminal.")
        except Exception as exc:  # noqa: BLE001
            self.app.log("Terminal: %s" % exc)

    def update_status(self, st, ui):
        set_pill(self.cards["usb"], bool(st.get("usb")), "CONNECTED", "OFFLINE")
        set_pill(self.cards["root"], bool(st.get("root")), "OPEN", "CLOSED")
        set_pill(self.cards["adb"], bool(st.get("adb")), "ONLINE", "OFFLINE")
        self.info["model"].configure(text="DJI Goggles N3")
        self.info["usb"].configure(text="2ca3:0020" if st.get("usb") else "—")
        adb = st.get("adb") or []
        self.info["adb"].configure(text=", ".join(str(x) for x in adb) or "—")
        self.info["ui"].configure(
            text=("patched" if ui.get("patched") else "stock") if ui.get("pid") else "—",
            text_color=theme.OK if ui.get("patched") else theme.TEXT)
        self.info["theme"].configure(
            text="purple" if ui.get("theme") else "stock",
            text_color=theme.ACCENT if ui.get("theme") else theme.TEXT)
        self.info["background"].configure(
            text="custom" if ui.get("background") else "stock")
        self.info["mods"].configure(text="on" if ui.get("mods") else "off")


class GogglesPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)
        self._photo = None
        self._last = 0.0
        self._recording = False

        left = card(self)
        left.grid(row=0, column=0, padx=7, pady=7, sticky="nsew")
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        lbl(top, "Live preview", 15, True).pack(side="left")
        self.fps = pill(top, "OFF")
        self.fps.pack(side="right")
        self.res = ctk.CTkOptionMenu(
            top, values=[label for label, _ in RESOLUTIONS], width=150,
            font=theme.font(11), fg_color=theme.CARD_ALT,
            button_color=theme.CARD_ALT, button_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT, dropdown_fg_color=theme.CARD,
            dropdown_text_color=theme.TEXT, command=self._res_changed)
        self.res.set(RESOLUTIONS[0][0])
        self.res.pack(side="right", padx=6)
        self.preview = ctk.CTkLabel(left, text="Live preview off",
                                    fg_color="#05040A", corner_radius=10,
                                    width=640, height=360,
                                    font=theme.font(13), text_color=theme.DIM)
        self.preview.pack(padx=16, pady=6)
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 14))
        self.start_btn = btn(row, "Start live", self.start_live, accent=True)
        self.start_btn.pack(side="left")
        self.stop_btn = btn(row, "Stop", self.stop_live)
        self.stop_btn.pack(side="left", padx=6)
        self.shot_btn = btn(row, "Screenshot", self.screenshot)
        self.shot_btn.pack(side="left", padx=6)
        self.rec_btn = btn(row, "Record 10s", self.toggle_record)
        self.rec_btn.pack(side="left", padx=6)
        muted(left, "Live preview restarts the goggles UI and loads n3live. "
                    "Resolution is selectable up to 1920x1080; higher sizes "
                    "lower the fps.",
              11).pack(anchor="w", padx=16, pady=(0, 12))

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, padx=7, pady=7, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)

        quick = card(right)
        quick.grid(row=0, column=0, sticky="ew")
        lbl(quick, "Quick actions", 15, True).pack(anchor="w", padx=16, pady=(14, 8))
        q = ctk.CTkFrame(quick, fg_color="transparent")
        q.pack(fill="x", padx=12, pady=(0, 12))
        q.grid_columnconfigure((0, 1), weight=1)
        for i, (text, cmd, acc) in enumerate([
                ("Purple theme", lambda: self.apply_theme("Purple"), True),
                ("Menu-only theme", lambda: self.apply_theme("Menu only"), False),
                ("E420Z stock row", self.install_stock_row, False),
                ("Custom menu", self.install_menu, False),
                ("Menu toggle", self.toggle_menu, False),
                ("Choose background", self.pick_background, False),
                ("Remove background", self.remove_background, False),
                ("Recover stock UI", self.recover_stock, False)]):
            b = btn(q, text, cmd, accent=acc)
            b.grid(row=i // 2, column=i % 2, padx=4, pady=4, sticky="ew")
        lbl(quick, "⚠ Custom menu/overlay is experimental. A prior display-hook "
                   "build black-screened. If the screen goes black, use "
                   "Recover stock UI or power-cycle.",
            10, False, theme.WARN, wraplength=300, justify="left").pack(
                anchor="w", padx=16, pady=(0, 12))

        state = card(right)
        state.grid(row=1, column=0, sticky="ew", pady=7)
        lbl(state, "Device state", 15, True).pack(anchor="w", padx=16, pady=(14, 6))
        self.state = {}
        for k, name in [("ui", "UI"), ("theme", "Theme"),
                        ("background", "Background"), ("menu", "Menu mod")]:
            row = ctk.CTkFrame(state, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            muted(row, name, 12).pack(side="left")
            v = lbl(row, "—", 12, True)
            v.pack(side="right")
            self.state[k] = v
        ctk.CTkLabel(state, text="", height=4).pack()

        logc = card(right)
        logc.grid(row=2, column=0, sticky="nsew")
        lbl(logc, "Recent", 15, True).pack(anchor="w", padx=16, pady=(14, 4))
        self.recent = ctk.CTkTextbox(logc, fg_color="#0A0710", height=140,
                                     font=theme.font(11, mono=True),
                                     text_color=theme.MUTED, wrap="word")
        self.recent.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.recent.configure(state="disabled")

    def update_status(self, st, ui):
        self.state["ui"].configure(
            text=("patched" if ui.get("patched") else "stock") if ui.get("pid") else "—")
        self.state["theme"].configure(
            text="purple" if ui.get("theme") else "stock",
            text_color=theme.ACCENT if ui.get("theme") else theme.TEXT)
        self.state["background"].configure(
            text="custom" if ui.get("background") else "stock")
        self.state["menu"].configure(text="loaded" if ui.get("mods") else "off")

    def _app_mods(self):
        m = modman.find("n3menu")
        if m and m.get("installed"):
            return ["/vendor/n3menu.so"]
        return []

    def _res_changed(self, label):
        scale = SCALE_BY_LABEL.get(label, 12)
        if self.app.live.running:
            self.app.live.set_scale(scale)
        else:
            self.app.log("Live resolution set to %s (applies on start)." % label)

    def start_live(self):
        if not messagebox.askyesno(
                "Live preview",
                "Starting live preview restarts the goggles UI and loads the "
                "n3live debug mod.\n\nContinue?"):
            return
        scale = SCALE_BY_LABEL.get(self.res.get(), 12)
        self.app.run_task(
            lambda: self.app.live.start(self._app_mods(), scale),
            "Start live preview",
            on_done=lambda *_: self.app.refresh_status())

    def stop_live(self):
        self.app.run_task(self.app.live.stop, "Stop live preview")

    def screenshot(self):
        self.app.run_task(
            lambda: capture_png(self._app_mods(), SHOTS, log=self.app.log),
            "Screenshot", on_done=self._shot_done)

    def _shot_done(self, path, err):
        if not err and path:
            self.app.log("Saved %s" % path)
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                pass

    def toggle_record(self):
        if not self.app.live.running:
            self.app.log("Start live preview before recording.")
            return
        if not self._recording:
            self.app.live.begin_record()
            self._recording = True
            self.rec_btn.configure(text="Stop & save")
            self.app.log("Recording live preview…")
            self.app.after(10000, self._finish_record)
        else:
            self._finish_record()

    def _finish_record(self):
        if not self._recording:
            return
        self._recording = False
        self.rec_btn.configure(text="Record 10s")
        path = os.path.join(SHOTS, "live_%s.gif" %
                            datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
        os.makedirs(SHOTS, exist_ok=True)
        self.app.run_task(lambda: self.app.live.end_record(path),
                          "Save recording",
                          on_done=lambda r, e: self.app.log(
                              "Saved %s" % (r[0] if r else path) if not e
                              else "Record failed: %s" % e))

    def push_frame(self, img):
        now = time.monotonic()
        if now - self._last < 0.033:
            return
        self._last = now
        self._show_frame(img)

    def _show_frame(self, img):
        img = img.resize((640, 360), Image.NEAREST)
        self._photo = ImageTk.PhotoImage(img)
        self.preview.configure(image=self._photo, text="")

    def set_fps(self, fps, size):
        if fps <= 0:
            self.fps.configure(text="OFF", fg_color=theme.CARD_ALT,
                               text_color=theme.MUTED)
        else:
            res = "%dx%d" % (size[0], size[1]) if size and size[0] else ""
            self.fps.configure(
                text=("%s · %.0f FPS" % (res, fps)) if res else "%.0f FPS" % fps,
                fg_color=theme.OK, text_color="#06110A")

    def append_recent(self, text):
        self.recent.configure(state="normal")
        self.recent.insert("end", text + "\n")
        self.recent.see("end")
        self.recent.configure(state="disabled")

    def apply_theme(self, preset):
        self.app.apply_theme(preset)

    def install_stock_row(self):
        if not messagebox.askyesno(
                "E420Z stock row",
                "Install a native E420Z row in the stock goggles menu?\n\n"
                "It adds a new E420Z row at the top and keeps Status, Album, "
                "Transmission and Settings. Opening it shows the stock "
                "Settings-style content panel beside the sidebar. No overlay, "
                "no input hooks. A reboot restores the original menu.\n\n"
                "The row is added at runtime by /vendor/n3menuinject.so, so "
                "/vendor/libew_gls.so is not modified."):
            return

        def work():
            ok = modman.install("n3menuinject", log=self.app.log)
            if not ok:
                return False
            n3ctl.ensure_adb(log=self.app.log)
            n3ctl.run_root("touch /data/local/tmp/n3menuinject_on",
                           timeout=8, retries=1)
            n3ctl.start_ui(log=self.app.log, mods=modman.mods_for_ui())
            return True

        self.app.run_task(work, "Install E420Z stock row",
                          on_done=lambda *_: self.app.refresh_status())

    def install_menu(self):
        if not messagebox.askyesno(
                "Custom menu",
                "Push the N3 menu mod and restart the UI?\n\n"
                "Short-press the 5-way center to select; long-press 5-way UP "
                "to open/close the menu. Short up/down navigate. The power "
                "button is not an input key on this unit, so it cannot be used.\n\n"
                "Display hooks are off in this build; it is the conservative "
                "version."):
            return

        def work():
            ok = modman.install("n3menu", log=self.app.log)
            if not ok:
                return False
            loader = os.path.join(APP_DIR, "assets", "mods", "n3mods.so")
            with n3ctl.vendor_write(log=self.app.log):
                if os.path.exists(loader):
                    n3ctl.push_file(loader, "/vendor/n3mods.so",
                                    log=self.app.log)
                    n3ctl.run_root("chmod 644 /vendor/n3mods.so",
                                   timeout=8, retries=1)
                n3ctl.run_root(
                    "rm -f /data/local/tmp/n3_menu_toggle "
                    "/data/local/tmp/n3_app_on",
                    timeout=8, retries=1)
            n3ctl.start_ui(log=self.app.log, mods=modman.mods_for_ui())
            return True

        self.app.run_task(work, "Install + start N3 menu",
                          on_done=lambda *_: self.app.refresh_status())

    def toggle_menu(self):
        def work():
            if not n3ctl.is_root():
                n3ctl.start_root(log=self.app.log)
            out = n3ctl.run_root(
                "test -f /data/local/tmp/n3_app_on && echo ON || echo OFF",
                timeout=8, retries=1)
            if "ON" in out:
                n3ctl.run_root("rm -f /data/local/tmp/n3_app_on",
                               timeout=8, retries=1)
                return "Menu hidden"
            n3ctl.run_root("touch /data/local/tmp/n3_app_on",
                           timeout=8, retries=1)
            return "Menu shown"

        self.app.run_task(work, "Toggle menu",
                          on_done=lambda out, err: self.app.log(
                              err or str(out)))

    def pick_background(self):
        path = filedialog.askopenfilename(
            title="Background image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp")])
        if not path:
            return
        self.app.run_task(
            lambda: background.install(path, None, log=self.app.log,
                                       mods=modman.mods_for_ui()),
            "Apply background", on_done=lambda *_: self.app.refresh_status())

    def remove_background(self):
        self.app.run_task(
            lambda: background.remove(log=self.app.log, mods=modman.mods_for_ui()),
            "Remove background", on_done=lambda *_: self.app.refresh_status())

    def recover_stock(self):
        if messagebox.askyesno("Recover stock UI", "Restart the stock goggles UI?"):
            self.app.run_task(lambda: n3ctl.start_stock_ui(log=self.app.log),
                              "Recover stock UI",
                              on_done=lambda *_: self.app.refresh_status())


class ShellPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.history = []
        self.hist_idx = 0

        bar = card(self)
        bar.grid(row=0, column=0, padx=7, pady=7, sticky="ew")
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        lbl(row, "Root shell", 15, True).pack(side="left")
        btn(row, "Start", self.start_root, accent=True).pack(side="right", padx=4)
        btn(row, "Stop", self.stop_root).pack(side="right", padx=4)
        btn(row, "Recover stock", self.recover).pack(side="right", padx=4)
        btn(row, "Copy", self.copy).pack(side="right", padx=4)
        btn(row, "Clear", self.clear).pack(side="right", padx=4)

        console = card(self)
        console.grid(row=1, column=0, padx=7, pady=7, sticky="nsew")
        self.text = ctk.CTkTextbox(console, fg_color="#07050C",
                                   text_color="#D8D2E8",
                                   font=theme.font(12, mono=True), wrap="none")
        self.text.pack(fill="both", expand=True, padx=12, pady=12)
        self.text.insert("end", "N3 ROOT shell console\n"
                                "Each command runs as uid 0 in dji_services.\n\n")
        self.text.configure(state="disabled")

        entry = card(self)
        entry.grid(row=2, column=0, padx=7, pady=7, sticky="ew")
        row = ctk.CTkFrame(entry, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        self.cmd = ctk.CTkEntry(row, placeholder_text="command…",
                                fg_color="#07050C", border_color=theme.BORDER,
                                font=theme.font(12, mono=True))
        self.cmd.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.cmd.bind("<Return>", lambda _e: self.send())
        self.cmd.bind("<Up>", lambda _e: self._hist(-1))
        self.cmd.bind("<Down>", lambda _e: self._hist(1))
        btn(row, "Send", self.send, accent=True).pack(side="right")

    def append(self, text):
        self.text.configure(state="normal")
        self.text.insert("end", text + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _hist(self, direction):
        if not self.history:
            return "break"
        self.hist_idx = max(0, min(len(self.history) - 1,
                                   self.hist_idx + direction))
        self.cmd.delete(0, "end")
        self.cmd.insert(0, self.history[self.hist_idx])
        return "break"

    def send(self):
        cmd = self.cmd.get().strip()
        if not cmd:
            return
        self.cmd.delete(0, "end")
        self.history.append(cmd)
        self.hist_idx = len(self.history)
        self.append("$ " + cmd)
        self.app.run_task(lambda: self._run(cmd), "shell: " + cmd[:40])

    def _run(self, cmd):
        if not n3ctl.is_root():
            n3ctl.start_root(log=self.app.log)
        out = n3ctl.run_root(cmd, timeout=40, retries=1)
        text = out.rstrip() if out.strip() else "(no output)"
        self.app.post(lambda: self.append(text))

    def start_root(self):
        self.app.run_task(lambda: n3ctl.start_root(log=self.app.log), "Start root")

    def stop_root(self):
        self.app.run_task(lambda: n3ctl.stop_root(log=self.app.log), "Stop root")

    def recover(self):
        self.app.run_task(lambda: n3ctl.start_stock_ui(log=self.app.log),
                          "Recover stock UI")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.text.get("1.0", "end"))
            self.app.log("Console copied.")
        except Exception:
            pass


class ModsPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        left = card(self)
        left.grid(row=0, column=0, padx=7, pady=7, sticky="nsew")
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))
        lbl(top, "Mods", 15, True).pack(side="left")
        btn(top, "Refresh", self.refresh).pack(side="right")
        self.list = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=8, pady=8)

        right = card(self)
        right.grid(row=0, column=1, padx=7, pady=7, sticky="nsew")
        lbl(right, "UI & theme", 15, True).pack(anchor="w", padx=16, pady=(14, 6))
        q = ctk.CTkFrame(right, fg_color="transparent")
        q.pack(fill="x", padx=12, pady=4)
        q.grid_columnconfigure(0, weight=1)
        for i, (text, cmd, acc) in enumerate([
                ("Apply Purple theme", lambda: self.apply_theme("Purple"), True),
                ("Apply Menu-only theme", lambda: self.apply_theme("Menu only"), False),
                ("Choose background", self.pick_background, False),
                ("Remove background", self.remove_background, False),
                ("Start UI with installed mods", self.start_ui, True),
                ("Revert to stock", self.revert, False)]):
            btn(q, text, cmd, accent=acc).grid(row=i, column=0, sticky="ew", pady=4)
        muted(right, "Mods are pushed to /vendor and loaded by n3mods.so at UI "
                     "start. Revert removes the theme/mod files.", 11,
              wraplength=320, justify="left").pack(anchor="w", padx=16, pady=(10, 14))

    def refresh(self):
        self.app.run_task(modman.refresh, "Refresh mods", on_done=self._render)

    def _render(self, rows, err):
        if err or not rows:
            return
        for w in self.list.winfo_children():
            w.destroy()
        for m in rows:
            row = ctk.CTkFrame(self.list, fg_color=theme.CARD_ALT,
                               corner_radius=10)
            row.pack(fill="x", pady=4, padx=2)
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            lbl(left, m.get("name", m.get("id")), 13, True).pack(anchor="w")
            line = "%s · v%s · %s" % (m.get("type", "mod"),
                                      m.get("version", "?"),
                                      m.get("risk", "medium"))
            muted(left, line, 11).pack(anchor="w")
            if m.get("experimental") or m.get("risk") in ("high", "medium"):
                lbl(left, "⚠ EXPERIMENTAL" if m.get("experimental")
                    else "⚠ REVIEW BEFORE USE", 10, True, theme.WARN).pack(anchor="w")
            if m.get("notes"):
                muted(left, m["notes"], 10, wraplength=430,
                      justify="left").pack(anchor="w", pady=(2, 0))
            inst = bool(m.get("installed"))
            b = btn(row, "Remove" if inst else "Install",
                    lambda mid=m["id"], on=inst: self.toggle(mid, on))
            b.pack(side="right", padx=10)

    def toggle(self, mid, installed):
        rec = modman.find(mid) or {}
        if (not installed and (rec.get("experimental") or
                               rec.get("risk") in ("high", "medium"))):
            if not messagebox.askyesno(
                    "Experimental mod",
                    "%s is marked %s risk%s.\n\nInstall it anyway?"
                    % (rec.get("name", mid), rec.get("risk", "medium"),
                       " (experimental)" if rec.get("experimental") else "")):
                return
        if installed:
            self.app.run_task(lambda: modman.uninstall(mid, log=self.app.log),
                              "Remove " + mid, on_done=lambda *_: self.refresh())
        else:
            self.app.run_task(lambda: modman.install(mid, log=self.app.log),
                              "Install " + mid, on_done=lambda *_: self.refresh())

    def apply_theme(self, preset):
        self.app.apply_theme(preset)

    def pick_background(self):
        path = filedialog.askopenfilename(
            title="Background image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp")])
        if path:
            self.app.run_task(
                lambda: background.install(path, None, log=self.app.log,
                                           mods=modman.mods_for_ui()),
                "Apply background", on_done=lambda *_: self.app.refresh_status())

    def remove_background(self):
        self.app.run_task(
            lambda: background.remove(log=self.app.log, mods=modman.mods_for_ui()),
            "Remove background", on_done=lambda *_: self.app.refresh_status())

    def start_ui(self):
        self.app.run_task(
            lambda: n3ctl.start_ui(log=self.app.log, mods=modman.mods_for_ui()),
            "Start UI with mods", on_done=lambda *_: self.app.refresh_status())

    def revert(self):
        if messagebox.askyesno("Revert to stock",
                               "Remove theme/mod/background files and start stock UI?"):
            self.app.run_task(lambda: n3ctl.revert_stock(log=self.app.log),
                              "Revert to stock",
                              on_done=lambda *_: self.app.refresh_status())


class LogsPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        bar = card(self)
        bar.grid(row=0, column=0, padx=7, pady=7, sticky="ew")
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        lbl(row, "Logs", 15, True).pack(side="left")
        for name, path in [("natartos", "/data/local/tmp/natartos.log"),
                           ("n3mods", "/data/local/tmp/n3mods.log"),
                           ("dji_glasses", "/data/local/tmp/dji_glasses.log"),
                           ("texttint", "/data/local/tmp/n3_texttint.log")]:
            btn(row, name, lambda p=path: self.tail(p)).pack(side="right", padx=3)
        btn(row, "Clear", self.clear).pack(side="right", padx=3)
        body = card(self)
        body.grid(row=1, column=0, padx=7, pady=7, sticky="nsew")
        self.text = ctk.CTkTextbox(body, fg_color="#07050C",
                                   font=theme.font(11, mono=True),
                                   text_color="#D8D2E8", wrap="none")
        self.text.pack(fill="both", expand=True, padx=12, pady=12)

    def append(self, text):
        self.text.insert("end", text + "\n")
        self.text.see("end")

    def clear(self):
        self.text.delete("1.0", "end")

    def tail(self, path):
        def work():
            if not n3ctl.is_root():
                n3ctl.start_root(log=self.app.log)
            return n3ctl.run_root("tail -n 200 %s 2>/dev/null" % path,
                                  timeout=12, retries=1)
        self.app.run_task(work, "tail " + os.path.basename(path),
                          on_done=lambda out, err: self.append(
                              "\n===== %s =====\n%s" %
                              (path, (out or "").rstrip() if not err else err)))


class SettingsPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        info = card(self)
        info.pack(fill="x", padx=7, pady=7)
        lbl(info, "Paths", 15, True).pack(anchor="w", padx=16, pady=(14, 6))
        for name, path in [("App", APP_DIR), ("Tools", n3ctl.TOOLS),
                           ("ADB", n3ctl.find_adb() or "not found"),
                           ("Stock lib", STOCK_LIB if os.path.exists(STOCK_LIB)
                            else "missing (theme building disabled)")]:
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            muted(row, name, 12).pack(side="left")
            lbl(row, path, 11, True).pack(side="right")
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=10)
        btn(row, "Open app folder", lambda: self.open(APP_DIR)).pack(side="left")
        btn(row, "Open tools", lambda: self.open(n3ctl.TOOLS)).pack(side="left", padx=6)
        btn(row, "Open screenshots", lambda: self.open(SHOTS)).pack(side="left")

        opts = card(self)
        opts.pack(fill="x", padx=7, pady=7)
        lbl(opts, "Behaviour", 15, True).pack(anchor="w", padx=16, pady=(14, 6))
        self.auto = tk.BooleanVar(value=True)
        row = ctk.CTkFrame(opts, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        muted(row, "Auto-refresh connection status", 12).pack(side="left")
        ctk.CTkSwitch(row, text="", variable=self.auto,
                      progress_color=theme.ACCENT).pack(side="right")
        self.restore = tk.BooleanVar(value=True)
        row = ctk.CTkFrame(opts, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 14))
        muted(row, "Restore stock USB when the app closes", 12).pack(side="left")
        ctk.CTkSwitch(row, text="", variable=self.restore,
                      progress_color=theme.ACCENT).pack(side="right")

        about = card(self)
        about.pack(fill="x", padx=7, pady=7)
        lbl(about, "N3 ROOT v%s" % VERSION, 15, True).pack(anchor="w", padx=16, pady=(14, 4))
        muted(about, "Session-only. No /system, dm-verity, OTP/RPMB or bootloader "
                     "changes. Recover stock UI is always available.", 12,
              wraplength=700, justify="left").pack(anchor="w", padx=16, pady=(0, 14))

    def open(self, path):
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.app.log("Open folder: %s" % exc)


class SparrowPage(ctk.CTkFrame):
    """Sparrow2 (DJI 5.8 GHz) console + factory-test surface.

    Read-only diagnostics. The shipped sdr_shell console is only reachable in
    factory/test mode; in normal mode DUSS returns -1002/-1007. This page shows
    that honestly instead of pretending the console works.
    """

    FW_DIR = "/vendor/modem_firmware/sparrow2"

    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = card(self)
        head.grid(row=0, column=0, padx=7, pady=7, sticky="ew")
        lbl(head, "Sparrow2 — internal 5.8 GHz", 15, True).pack(
            anchor="w", padx=16, pady=(14, 4))
        muted(head, "Sparrow2 is DJI's radio SoC (USB product string C5, "
                    "2ca3:1020). ESP32-C5 is a different, unrelated chip.",
              12, wraplength=900, justify="left").pack(
            anchor="w", padx=16, pady=(0, 4))
        muted(head, "The AP has no IQ/ADC device. A shipped console exists "
                    "(/system/bin/sdr_shell), but the test:7 DUSS host is the "
                    "factory PC fixture. A factory-flag attempt did not register "
                    "it (queries return -1002/-1007). AP-side Sparrow2 channels "
                    "are logs/dumps only.", 12,
              wraplength=900, justify="left").pack(
            anchor="w", padx=16, pady=(0, 14))

        acts = card(self)
        acts.grid(row=1, column=0, padx=7, pady=(0, 7), sticky="ew")
        row = ctk.CTkFrame(acts, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        btn(row, "Firmware inventory", self.inventory).pack(side="left")
        btn(row, "List Sparrow2 tools", self.tools).pack(side="left", padx=6)
        btn(row, "Console help (read-only)", self.console_help,
            accent=True).pack(side="left", padx=6)
        btn(row, "Sparrow2 summary", self.open_summary).pack(side="left")
        btn(row, "Load findings", self.load_findings).pack(side="left", padx=6)
        btn(row, "Generate report", self.report).pack(side="left", padx=6)
        btn(row, "Bulk console probe", self.bulk_probe).pack(side="left", padx=6)
        btn(row, "Radio probe doc", self.open_doc).pack(side="left", padx=6)

        body = card(self)
        body.grid(row=2, column=0, padx=7, pady=7, sticky="nsew")
        self.text = ctk.CTkTextbox(body, fg_color="#07050C",
                                   font=theme.font(11, mono=True),
                                   text_color="#D8D2E8", wrap="none")
        self.text.pack(fill="both", expand=True, padx=12, pady=12)
        self.append("Select a probe. Nothing here writes to the goggles or "
                    "enters factory mode.\n")

    def append(self, text):
        self.text.insert("end", text + "\n")
        self.text.see("end")

    def _run(self, cmd, label, timeout=40):
        def work():
            if not n3ctl.is_root():
                n3ctl.start_root(log=self.app.log)
            return n3ctl.run_root(cmd, timeout=timeout, retries=1)

        self.app.run_task(
            work, label,
            on_done=lambda out, err: self.append(
                "\n===== %s =====\n%s" %
                (label, (out or "").rstrip() if not err else err)))

    def inventory(self):
        self._run("ls -l %s 2>/dev/null; echo; ls -d %s/*/ 2>/dev/null"
                  % (self.FW_DIR, self.FW_DIR), "firmware inventory")

    def tools(self):
        self._run("ls -l /system/bin/sdr_shell "
                  "/system/bin/test_sparrow2_link.sh "
                  "/system/bin/test_sparrow2_tsync.sh "
                  "/system/bin/test_sparrow2_hw_ver.sh "
                  "/system/bin/test_reset_s2_link.sh "
                  "/system/bin/test_sdrlog_e3t_uart5_link.sh "
                  "/system/bin/test_rf.sh 2>/dev/null", "sparrow2 tools")

    def console_help(self):
        self.append("\n[console] sending sdr_shell 'help' (read-only). "
                    "On-device this is expected to return -1002/-1007: the "
                    "test:7 host is the factory PC fixture, not a local service.")
        self._run("timeout 12 /system/bin/sdr_shell help 2>&1; "
                  "echo '--- raw ---'; "
                  "dji_mb_ctrl -S test -R diag -m 2304 -o 3000000 -g 14 -t 0 "
                  "-s 9 -c 0x55 0064001868656c700d 2>&1 | tail -6",
                  "sdr_shell help", timeout=45)

    def _open(self, name):
        path = os.path.abspath(os.path.join(APP_DIR, "..", "docs", name))
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.app.log("Open doc: %s" % exc)

    def open_doc(self):
        self._open("RADIO-PROBE.md")

    def open_summary(self):
        self._open("SPARROW2.md")

    def load_findings(self):
        path = os.path.abspath(os.path.join(APP_DIR, "..", "docs",
                                            "SPARROW2.md"))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self.append("\n===== SPARROW2.md =====\n" + fh.read())
        except Exception as exc:  # noqa: BLE001
            self.app.log("Load findings: %s" % exc)

    REPORT_CMDS = [
        ("identity", "getprop ro.boot.mode; getprop sys.usb.config; "
                     "cat /proc/cmdline"),
        ("firmware", "ls -l /vendor/modem_firmware/sparrow2/ 2>/dev/null"),
        ("tools", "ls -l /system/bin/sdr_shell "
                  "/system/bin/test_sparrow2_link.sh "
                  "/system/bin/test_sparrow2_tsync.sh "
                  "/system/bin/test_sparrow2_hw_ver.sh "
                  "/system/bin/test_reset_s2_link.sh "
                  "/system/bin/test_sdrlog_e3t_uart5_link.sh "
                  "/system/bin/test_rf.sh 2>/dev/null"),
        ("duss_hosts", "grep -a '@/duss/mb' /proc/net/unix 2>/dev/null "
                       "| sed 's/.*@/@/' | sort -u"),
        ("host_1e07", "grep -c '@/duss/mb/0x1e07' /proc/net/unix 2>/dev/null"),
        ("sdr_shell_help", "timeout 12 /system/bin/sdr_shell help 2>&1"),
    ]

    def report(self):
        def work():
            if not n3ctl.is_root():
                n3ctl.start_root(log=self.app.log)
            parts = ["# Sparrow2 report (read-only)", ""]
            for name, cmd in self.REPORT_CMDS:
                try:
                    out = n3ctl.run_root(cmd, timeout=30, retries=1)
                except Exception as exc:  # noqa: BLE001
                    out = "ERROR: %s" % exc
                parts.append("## %s\n```\n%s\n```" % (name, out.strip()))
            text = "\n\n".join(parts)
            path = os.path.join(APP_DIR, "state", "sparrow2_report.md")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(text)
            return text + "\n\nsaved: %s" % path

        self.app.run_task(
            work, "sparrow2 report",
            on_done=lambda out, err: self.append(err or out))

    def bulk_probe(self):
        """Experimental: custom -J bulk route to Sparrow2, read-only help."""
        import json as _json

        def work():
            if not n3ctl.is_root():
                n3ctl.start_root(log=self.app.log)
            raw = n3ctl.run_root("cat /system/etc/dji.json",
                                 timeout=40, retries=1)
            base = _json.loads(raw)
            probe = bulkmod.build_probe(base, 9)
            text = _json.dumps(probe, separators=(",", ":"))
            local = os.path.join(APP_DIR, "state", "n3_sparrow_probe.json")
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "w", encoding="utf-8") as fh:
                fh.write(text)
            if not n3ctl.push_file(local, bulkmod.REMOTE_JSON,
                                   log=self.app.log):
                raise RuntimeError("push failed")
            cmd = ("dji_mb_ctrl -J %s -S sparrow_probe -R link -m 2304 "
                   "-o 4000000 -g 14 -t 0 -s 9 -c 0x55 0064001868656c700d "
                   "2>&1" % bulkmod.REMOTE_JSON)
            try:
                return n3ctl.run_root(cmd, timeout=45, retries=1)
            finally:
                n3ctl.run_root("rm -f %s" % bulkmod.REMOTE_JSON,
                               timeout=10, retries=1)

        self.app.run_task(
            work, "bulk console probe",
            on_done=lambda out, err: self.append(err or out),
            confirm="Experimental: sends a read-only 'help' query to Sparrow2 "
                    "over /bulk/s2 using a custom DUSS route. Continue?")


class App(ctk.CTk):
    def __init__(self):
        theme.setup()
        super().__init__(fg_color=theme.BG)
        self.title("N3 ROOT — DJI Goggles N3")
        self.geometry("1280x820")
        self.minsize(1120, 720)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.log_lines = []
        self.status_data = {}
        self.ui_data = {}
        self._status_busy = False
        self._closing = False
        self.ui_q: queue.Queue = queue.Queue()
        self.live = LiveStream(self.log, self._live_frame, self._live_status)
        self._build_sidebar()
        self._build_main()
        self._make_pages()
        self.show_page("connection")
        self.after(300, self.refresh_status)
        self.after(50, self._poll_ui)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- layout
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=228, corner_radius=0,
                            fg_color=theme.SIDEBAR)
        side.grid(row=0, column=0, rowspan=3, sticky="nsew")
        side.grid_propagate(False)
        side.grid_rowconfigure(8, weight=1)
        lbl(side, "N3 ROOT", 22, True, theme.ACCENT).grid(
            row=0, column=0, padx=20, pady=(22, 0), sticky="w")
        muted(side, "Goggles N3 control deck").grid(
            row=1, column=0, padx=20, pady=(0, 18), sticky="w")
        self.nav = {}
        items = [("connection", "Connection", "◈"),
                 ("goggles", "E42OZ", "◉"),
                 ("sparrow", "Sparrow2", "✦"),
                 ("shell", "Root Shell", "▣"),
                 ("mods", "Mods & UI", "◆"),
                 ("logs", "Logs", "≡"),
                 ("settings", "Settings", "⚙")]
        for i, (key, text, icon) in enumerate(items):
            b = ctk.CTkButton(side, text="  %s   %s" % (icon, text), anchor="w",
                              fg_color="transparent", hover_color=theme.CARD,
                              text_color=theme.MUTED,
                              font=theme.font(13), corner_radius=10, height=42,
                              command=lambda k=key: self.show_page(k))
            b.grid(row=2 + i, column=0, padx=12, pady=3, sticky="ew")
            self.nav[key] = b
        self.side_status = ctk.CTkLabel(side, text="●  disconnected",
                                        font=theme.font(11), text_color=theme.DIM)
        self.side_status.grid(row=9, column=0, padx=20, pady=(0, 18), sticky="w")
        muted(side, "v%s · experimental · session-only" % VERSION, 10).grid(
            row=10, column=0, padx=20, pady=(0, 16), sticky="w")

    def _build_main(self):
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 0))
        head.grid_columnconfigure(0, weight=1)
        self.page_title = lbl(head, "Connection", 22, True)
        self.page_title.grid(row=0, column=0, sticky="w")
        self.pill_adb = pill(head, "ADB —")
        self.pill_adb.grid(row=0, column=1, padx=4)
        self.pill_root = pill(head, "ROOT —")
        self.pill_root.grid(row=0, column=2, padx=4)
        self.pill_ui = pill(head, "UI —")
        self.pill_ui.grid(row=0, column=3, padx=4)
        btn(head, "Refresh", self.refresh_status).grid(row=0, column=4, padx=(10, 0))

        self.host = ctk.CTkFrame(self, fg_color="transparent")
        self.host.grid(row=1, column=1, sticky="nsew", padx=12, pady=8)
        self.host.grid_rowconfigure(0, weight=1)
        self.host.grid_columnconfigure(0, weight=1)
        self.statusbar = ctk.CTkLabel(self, text="Ready.", anchor="w",
                                      font=theme.font(11), text_color=theme.MUTED,
                                      fg_color=theme.SIDEBAR, height=26)
        self.statusbar.grid(row=2, column=1, sticky="ew", padx=0, pady=0)

    def _make_pages(self):
        self.pages = {}
        self.page_classes = {
            "connection": ConnectionPage,
            "goggles": GogglesPage,
            "sparrow": SparrowPage,
            "shell": ShellPage,
            "mods": ModsPage,
            "logs": LogsPage,
            "settings": SettingsPage,
        }
        for key, cls in self.page_classes.items():
            page = cls(self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.mods_page = self.pages["mods"]
        self.goggles_page = self.pages["goggles"]
        self.after(400, self.mods_page.refresh)

    def show_page(self, key):
        for k, b in self.nav.items():
            b.configure(fg_color=theme.CARD if k == key else "transparent",
                        text_color=theme.ACCENT if k == key else theme.MUTED)
        self.page_title.configure(text={
            "connection": "Connection", "goggles": "E42OZ — Goggles",
            "sparrow": "Sparrow2 — 5.8 GHz radio",
            "shell": "Root Shell", "mods": "Mods & UI",
            "logs": "Logs", "settings": "Settings"}[key])
        self.pages[key].tkraise()

    # ------------------------------------------------------------------ log
    def log(self, msg):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = "[%s] %s" % (stamp, msg)
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-500:]
        print(line)
        self.ui_q.put(("log", line))

    def post(self, fn):
        self.ui_q.put(("call", fn))

    def _poll_ui(self):
        if self._closing:
            return
        try:
            for _ in range(60):
                kind, payload = self.ui_q.get_nowait()
                if kind == "log":
                    self.statusbar.configure(text=payload)
                    if hasattr(self, "goggles_page"):
                        self.goggles_page.append_recent(payload)
                elif kind == "status":
                    self.apply_status(*payload)
                elif kind == "frame":
                    self.goggles_page.push_frame(payload)
                elif kind == "fps":
                    self.goggles_page.set_fps(*payload)
                elif kind == "call":
                    try:
                        payload()
                    except Exception as exc:  # noqa: BLE001
                        print("ui call failed:", exc)
        except queue.Empty:
            pass
        self.after(50, self._poll_ui)

    # ---------------------------------------------------------------- tasks
    def run_task(self, fn, label, on_done=None, confirm=None):
        if confirm and not messagebox.askyesno("Confirm", confirm):
            return
        self.log("… %s" % label)

        def work():
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001
                res, err = None, exc

            def fin():
                if err:
                    self.log("✖ %s: %s" % (label, err))
                else:
                    self.log("✔ %s" % label)
                if on_done:
                    on_done(res, err)
                self.refresh_status()
            self.post(fin)

        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------------------- status
    def refresh_status(self):
        if self._status_busy or self._closing:
            return
        self._status_busy = True

        def work():
            try:
                st, ui, err = n3ctl.status(), n3ctl.ui_state(), None
            except Exception as exc:  # noqa: BLE001
                st, ui, err = None, None, exc

            if err is None:
                self.ui_q.put(("status", (st, ui)))

            def fin():
                self._status_busy = False
                if not self._closing:
                    self.after(5000, self.refresh_status)
            self.post(fin)

        threading.Thread(target=work, daemon=True).start()

    def apply_status(self, st, ui):
        self.status_data, self.ui_data = st, ui
        adb_on = bool(st.get("adb"))
        root_on = bool(st.get("root"))
        ui_on = bool(ui.get("pid"))
        set_pill(self.pill_adb, adb_on, "ADB ON", "ADB OFF")
        set_pill(self.pill_root, root_on, "ROOT ON", "ROOT OFF")
        set_pill(self.pill_ui, ui_on, "UI " + ("PATCHED" if ui.get("patched") else "STOCK"),
                 "UI OFF")
        self.side_status.configure(
            text="●  connected" if (adb_on or root_on) else "●  disconnected",
            text_color=theme.OK if (adb_on or root_on) else theme.DIM)
        for page in self.pages.values():
            if hasattr(page, "update_status"):
                try:
                    page.update_status(st, ui)
                except Exception:
                    pass

    # ----------------------------------------------------------------- live
    def _live_frame(self, img):
        self.ui_q.put(("frame", img))

    def _live_status(self, fps, size):
        self.ui_q.put(("fps", (fps, size)))

    # --------------------------------------------------------------- themes
    def apply_theme(self, preset):
        if not os.path.exists(STOCK_LIB):
            messagebox.showerror(
                "Theme", "Missing stock lib:\n%s\n\nPlace the stock "
                "libew_gls.so there (it is intentionally not in git)." % STOCK_LIB)
            return
        loader = os.path.join(APP_DIR, "assets", "dji_glasses_vendor")
        if not os.path.exists(loader):
            messagebox.showerror(
                "Theme", "Missing UI loader:\n%s\n\nPlace dji_glasses_vendor "
                "there (extracted from your device; not in git)." % loader)
            return
        if not messagebox.askyesno(
                "Apply theme", "Build and install the '%s' theme?\n"
                "The UI will restart." % preset):
            return

        def build():
            out = os.path.join(APP_DIR, "state", "build",
                               "libew_gls_%s.so" % preset.replace(" ", "_").lower())
            os.makedirs(os.path.dirname(out), exist_ok=True)
            theme_builder.build(theme_builder.PRESETS[preset],
                                theme_builder.PRESET_ENABLED[preset],
                                STOCK_LIB, out, log=self.log)
            return n3ctl.install_theme(out, log=self.log,
                                       mods=modman.mods_for_ui())

        self.run_task(build, "Apply %s theme" % preset,
                      on_done=lambda *_: self.refresh_status())

    # ---------------------------------------------------------------- close
    def on_close(self):
        self._closing = True
        try:
            if self.live.running:
                self.live.stop()
        except Exception:
            pass
        try:
            if getattr(self.pages.get("settings"), "restore", None) and \
                    self.pages["settings"].restore.get():
                if n3ctl.is_root():
                    n3ctl.restore_stock(log=print)
                    n3ctl.stop_root(log=print)
        except Exception:
            pass
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
