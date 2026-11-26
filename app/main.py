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
from ui.components import (  # noqa: E402
    SafetyBadge, action_cell, action_row, btn, button_grid, card, empty_state,
    helper_note, lbl, log_textbox, muted, pill, section_header,
    set_pill, set_tile, status_row)
from ui.live import (LiveStream, capture_png, RESOLUTIONS,
                     SCALE_BY_LABEL)  # noqa: E402
from tools import probe_n3_bulk_console as bulkmod  # noqa: E402

STOCK_LIB = os.path.join(APP_DIR, "assets", "libew_gls_stock.so")
SHOTS = os.path.join(APP_DIR, "state", "shots")
VERSION = "1.0.0"

# Page title, one-line description and the highest safety level on the page.
PAGE_META = {
    "connection": ("Connection", "Device link, root session and recovery", "RISKY"),
    "goggles": ("E42OZ — Goggles", "Live preview, screenshots and UI mods", "EXPERIMENTAL"),
    "sparrow": ("Sparrow2 — 5.8 GHz radio", "Read-only radio diagnostics", "RISKY"),
    "shell": ("Root Shell", "Interactive uid 0 console on the goggles", "RISKY"),
    "mods": ("Mods & UI", "Themes, backgrounds and /vendor mods", "EXPERIMENTAL"),
    "logs": ("Logs", "Read-only on-device log tails", "SAFE"),
    "settings": ("Settings", "Paths, preferences and safety key", "SAFE"),
}

# Safety overrides for known mods. Anything not listed falls back to its
# plugin.json risk value.
MOD_SAFETY = {
    "capture": "SAFE",
    "background": "EXPERIMENTAL",
    "n3live": "EXPERIMENTAL",
    "n3menuinject": "EXPERIMENTAL",
    "n3menu": "EXPERIMENTAL",
    "paint": "EXPERIMENTAL",
}


def mod_safety_level(rec) -> str:
    rec = rec or {}
    known = MOD_SAFETY.get(rec.get("id"))
    if known:
        return known
    risk = str(rec.get("risk", "medium")).lower()
    if risk == "high":
        return "RISKY"
    if risk == "low" and not rec.get("experimental"):
        return "SAFE"
    return "EXPERIMENTAL"


class ConnectionPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.host, fg_color="transparent")
        self.app = app
        for c in range(3):
            self.grid_columnconfigure(c, weight=1)

        self.cards = {}
        specs = [("usb", "USB DEVICE", "libusb0 · dji_blackbox"),
                 ("root", "ROOT SHELL", "port 4444 · uid 0"),
                 ("adb", "ADB", "USB composition")]
        for i, (key, title, sub) in enumerate(specs):
            c = card(self)
            c.grid(row=0, column=i, padx=theme.PAGE_GAP, pady=theme.PAGE_GAP,
                   sticky="nsew")
            muted(c, title, 10).pack(anchor="w", padx=16, pady=(14, 0))
            big = lbl(c, "—", 22, True, theme.DIM)
            big.pack(anchor="w", padx=16, pady=(1, 0))
            muted(c, sub, 11).pack(anchor="w", padx=16, pady=(0, 14))
            self.cards[key] = big

        dev = card(self)
        dev.grid(row=1, column=0, columnspan=2, padx=theme.PAGE_GAP,
                 pady=theme.PAGE_GAP, sticky="nsew")
        section_header(dev, "Goggles", "Read-only device summary", "SAFE",
                       padx=18, pady=(14, 4), wrap=520)
        self.info = {}
        for key, name in [("model", "Model"), ("usb", "USB"),
                          ("adb", "ADB serial"), ("ui", "UI"),
                          ("theme", "Theme"), ("background", "Background"),
                          ("mods", "Mods")]:
            self.info[key] = status_row(dev, name, padx=18)
        muted(dev, "Refreshed every 5 seconds.", 10).pack(
            anchor="w", padx=18, pady=(4, 14))

        act = card(self)
        act.grid(row=1, column=2, padx=theme.PAGE_GAP,
                 pady=theme.PAGE_GAP, sticky="nsew")
        section_header(act, "Actions", "Session, root and recovery",
                       None, padx=16, pady=(14, 4), wrap=300)
        grid = ctk.CTkFrame(act, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 4))
        actions = [
            ("Enable ADB", self.act_adb, True, "EXPERIMENTAL"),
            ("Start root", self.act_start_root, True, "RISKY"),
            ("Open root console", lambda: self.app.show_page("shell"),
             False, "RISKY"),
            ("Stop root", self.act_stop_root, False, "SAFE"),
            ("Recover stock UI", self.act_stock, False, "RISKY"),
            ("Restart patched UI", self.act_restart, False, "EXPERIMENTAL"),
            ("External terminal", self.act_terminal, False, "RISKY"),
        ]
        for text, cmd, acc, level in actions:
            action_row(grid, text, cmd, level, accent=acc, height=32, pady=1)
        helper_note(act,
                    "Root is session-only. Use Recover stock UI if a mod "
                    "black-screens.",
                    "RISKY", wraplength=250, padx=16, pady=(4, 12))

        helpc = card(self)
        helpc.grid(row=2, column=0, columnspan=3, padx=theme.PAGE_GAP,
                   pady=theme.PAGE_GAP, sticky="ew")
        section_header(helpc, "First run", "Get connected in four steps",
                       None, padx=18, pady=(14, 4), wrap=760)
        steps = [
            ("1", "Connect USB and power on the goggles."),
            ("2", "Start root (blackbox RCE), then enable ADB."),
            ("3", "Open E42OZ for live preview, screenshots and mods."),
            ("4", "Recover stock UI is always kept available."),
        ]
        for number, text in steps:
            row = ctk.CTkFrame(helpc, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=1)
            lbl(row, number, 11, True, theme.ACCENT).pack(side="left",
                                                          padx=(0, 10))
            lbl(row, text, 11, False, theme.MUTED).pack(side="left")
        helper_note(
            helpc,
            "Custom menu/overlay and display hooks can break rendering. "
            "See docs/EXPERIMENTAL.md. Use Recover stock UI if needed.",
            "EXPERIMENTAL", wraplength=760, padx=18, pady=(8, 14))

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
        set_tile(self.cards["usb"], bool(st.get("usb")), "CONNECTED", "OFFLINE")
        set_tile(self.cards["root"], bool(st.get("root")), "OPEN", "CLOSED")
        set_tile(self.cards["adb"], bool(st.get("adb")), "ONLINE", "OFFLINE")
        self.info["model"].configure(text="DJI Goggles N3")
        self.info["usb"].configure(text="2ca3:0020" if st.get("usb") else "—")
        adb = st.get("adb") or []
        self.info["adb"].configure(text=", ".join(str(x) for x in adb) or "—")
        self.info["ui"].configure(
            text=("patched" if ui.get("patched") else "stock") if ui.get("pid") else "—",
            text_color=theme.SAFE if ui.get("patched") else theme.TEXT)
        self.info["theme"].configure(
            text="purple" if ui.get("theme") else "stock",
            text_color=theme.ACCENT if ui.get("theme") else theme.TEXT)
        self.info["background"].configure(
            text="custom" if ui.get("background") else "stock",
            text_color=theme.EXPERIMENTAL if ui.get("background") else theme.TEXT)
        self.info["mods"].configure(
            text="on" if ui.get("mods") else "off",
            text_color=theme.EXPERIMENTAL if ui.get("mods") else theme.TEXT)


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
        left.grid(row=0, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="nsew")
        section_header(left, "Live preview",
                       "Mirrors the goggles screen over USB.", "EXPERIMENTAL",
                       padx=16, pady=(14, 4), wrap=560)

        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(0, 6))
        muted(top, "Resolution", 11).pack(side="left")
        self.fps = pill(top, "OFF")
        self.fps.pack(side="right")
        self.res = ctk.CTkOptionMenu(
            top, values=[label for label, _ in RESOLUTIONS], width=162,
            font=theme.font(11), fg_color=theme.CARD_ALT,
            button_color=theme.CARD_ALT, button_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT, dropdown_fg_color=theme.CARD,
            dropdown_text_color=theme.TEXT, command=self._res_changed)
        self.res.set(RESOLUTIONS[0][0])
        self.res.pack(side="left", padx=(8, 0))
        self.preview = ctk.CTkLabel(
            left,
            text="LIVE PREVIEW OFF\nStart live to mirror the goggles screen here.",
            fg_color=theme.CONSOLE, corner_radius=theme.RADIUS_CONTROL,
            border_width=1, border_color=theme.BORDER,
            width=480, height=270, font=theme.font(12),
            text_color=theme.DIM, justify="center")
        self.preview.pack(fill="both", expand=True, padx=16, pady=6)

        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 8))
        self.start_btn = btn(row, "Start live", self.start_live, accent=True)
        self.start_btn.pack(side="left")
        self.stop_btn = btn(row, "Stop", self.stop_live)
        self.stop_btn.pack(side="left", padx=6)
        self.shot_btn = btn(row, "Screenshot", self.screenshot)
        self.shot_btn.pack(side="left", padx=6)
        self.rec_btn = btn(row, "Record 10s", self.toggle_record)
        self.rec_btn.pack(side="left", padx=6)

        legend = ctk.CTkFrame(left, fg_color="transparent")
        legend.pack(fill="x", padx=16, pady=(0, 3))
        SafetyBadge(legend, "SAFE", compact=True).pack(side="left")
        muted(legend, "Stop · Screenshot", 10).pack(side="left", padx=(5, 14))
        SafetyBadge(legend, "EXPERIMENTAL", compact=True).pack(side="left")
        muted(legend, "Start live · Record", 10).pack(side="left", padx=(5, 0))
        muted(left, "Live preview restarts the goggles UI and loads n3live. "
                    "Higher resolutions lower the fps.", 10,
              wraplength=520, justify="left").pack(
            anchor="w", padx=16, pady=(0, 12))

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, padx=theme.PAGE_GAP,
                   pady=theme.PAGE_GAP, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)

        quick = card(right)
        quick.grid(row=0, column=0, sticky="ew")
        section_header(quick, "Quick actions", "Theme, menu and recovery",
                       None, padx=16, pady=(14, 4), wrap=300)
        q = ctk.CTkFrame(quick, fg_color="transparent")
        q.pack(fill="x", padx=12, pady=(0, 4))
        q.grid_columnconfigure((0, 1), weight=1)
        for i, (text, cmd, acc, level) in enumerate([
                ("Purple theme", lambda: self.apply_theme("Purple"),
                 True, "EXPERIMENTAL"),
                ("Menu-only theme", lambda: self.apply_theme("Menu only"),
                 False, "EXPERIMENTAL"),
                ("E420Z stock row", self.install_stock_row, False,
                 "EXPERIMENTAL"),
                ("Custom menu", self.install_menu, False, "EXPERIMENTAL"),
                ("Menu toggle", self.toggle_menu, False, "EXPERIMENTAL"),
                ("Choose background", self.pick_background, False,
                 "EXPERIMENTAL"),
                ("Remove background", self.remove_background, False,
                 "EXPERIMENTAL"),
                ("Recover stock UI", self.recover_stock, False, "RISKY")]):
            cell = action_cell(q, text, cmd, level, accent=acc, height=32)
            cell.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky="ew")
        helper_note(quick,
                    "Custom menu can black-screen. Use Recover stock UI or "
                    "power-cycle to restore.",
                    "EXPERIMENTAL", wraplength=280, padx=16, pady=(4, 12))

        state = card(right)
        state.grid(row=1, column=0, sticky="ew", pady=theme.PAGE_GAP)
        section_header(state, "Device state", None, "SAFE",
                       padx=16, pady=(14, 4), wrap=300)
        self.state = {}
        for k, name in [("ui", "UI"), ("theme", "Theme"),
                        ("background", "Background"), ("menu", "Menu mod")]:
            self.state[k] = status_row(state, name)
        ctk.CTkLabel(state, text="", height=4).pack()

        logc = card(right)
        logc.grid(row=2, column=0, sticky="nsew")
        section_header(logc, "Recent activity", None, "SAFE",
                       padx=16, pady=(14, 4), wrap=300)
        self.recent = log_textbox(logc, height=90, size=10, wrap="word")
        self.recent.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.recent.configure(state="disabled")

    def update_status(self, st, ui):
        self.state["ui"].configure(
            text=("patched" if ui.get("patched") else "stock") if ui.get("pid") else "—",
            text_color=theme.SAFE if ui.get("patched") else theme.TEXT)
        self.state["theme"].configure(
            text="purple" if ui.get("theme") else "stock",
            text_color=theme.ACCENT if ui.get("theme") else theme.TEXT)
        self.state["background"].configure(
            text="custom" if ui.get("background") else "stock",
            text_color=theme.EXPERIMENTAL if ui.get("background") else theme.TEXT)
        self.state["menu"].configure(
            text="loaded" if ui.get("mods") else "off",
            text_color=theme.EXPERIMENTAL if ui.get("mods") else theme.TEXT)

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
                "Live preview · EXPERIMENTAL",
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
        width = self.preview.winfo_width()
        height = self.preview.winfo_height()
        if width < 160 or height < 90:
            width, height = 640, 360
        scale = min(width / img.width, height / img.height)
        size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        self._photo = ImageTk.PhotoImage(img.resize(size, Image.NEAREST))
        self.preview.configure(image=self._photo, text="")

    def set_fps(self, fps, size):
        if fps <= 0:
            self.fps.configure(text="OFF", fg_color=theme.CARD_ALT,
                               text_color=theme.MUTED)
        else:
            res = "%dx%d" % (size[0], size[1]) if size and size[0] else ""
            self.fps.configure(
                text=("%s · %.0f FPS" % (res, fps)) if res else "%.0f FPS" % fps,
                fg_color=theme.SAFE_BG, text_color=theme.SAFE)

    def append_recent(self, text):
        self.recent.configure(state="normal")
        self.recent.insert("end", text + "\n")
        self.recent.see("end")
        self.recent.configure(state="disabled")

    def apply_theme(self, preset):
        self.app.apply_theme(preset)

    def install_stock_row(self):
        if not messagebox.askyesno(
                "E420Z stock row · EXPERIMENTAL",
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
                "Custom menu · EXPERIMENTAL",
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
        if messagebox.askyesno("Recover stock UI · RISKY",
                               "Restart the stock goggles UI?"):
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
        bar.grid(row=0, column=0, padx=theme.PAGE_GAP,
                 pady=theme.PAGE_GAP, sticky="ew")
        section_header(bar, "Root shell",
                       "Each command runs as uid 0 in dji_services.",
                       "RISKY", padx=16, pady=(14, 4), wrap=520)
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))
        btn(row, "Start", self.start_root, accent=True).pack(side="left")
        btn(row, "Stop", self.stop_root).pack(side="left", padx=6)
        btn(row, "Recover stock", self.recover).pack(side="left", padx=6)
        helper_note(bar,
                    "Session-only root. Review every command; Recover stock "
                    "restarts the goggles UI if it becomes unresponsive.",
                    "RISKY", wraplength=760, padx=16, pady=(0, 12))

        console = card(self)
        console.grid(row=1, column=0, padx=theme.PAGE_GAP,
                     pady=theme.PAGE_GAP, sticky="nsew")
        head = ctk.CTkFrame(console, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))
        lbl(head, "Output", 12, True).pack(side="left")
        muted(head, "monospace · scrollable", 10).pack(side="left", padx=(8, 0))
        btn(head, "Copy", self.copy, height=30).pack(side="right", padx=4)
        btn(head, "Clear", self.clear, height=30).pack(side="right", padx=4)

        self.text = log_textbox(console, height=240, size=12)
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.text.insert("end", "N3 ROOT shell console\n"
                                "Each command runs as uid 0 in dji_services.\n\n")
        self.text.configure(state="disabled")

        entry = card(self)
        entry.grid(row=2, column=0, padx=theme.PAGE_GAP,
                   pady=theme.PAGE_GAP, sticky="ew")
        row = ctk.CTkFrame(entry, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        lbl(row, "$", 12, True, theme.ACCENT, mono=True).pack(
            side="left", padx=(0, 8))
        self.cmd = ctk.CTkEntry(row, placeholder_text="command…",
                                fg_color=theme.CONSOLE,
                                border_color=theme.BORDER,
                                text_color=theme.TEXT_SOFT,
                                font=theme.font(12, mono=True),
                                height=36)
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
        left.grid(row=0, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="nsew")
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))
        title = ctk.CTkFrame(top, fg_color="transparent")
        title.pack(side="left")
        lbl(title, "Mods", 15, True).pack(side="left")
        SafetyBadge(title, "EXPERIMENTAL").pack(side="left", padx=(8, 0))
        muted(left, "Managed mods and plugins discovered on disk.", 11).pack(
            anchor="w", padx=14, pady=(0, 4))
        btn(top, "Refresh", self.refresh).pack(side="right")
        self.list = ctk.CTkScrollableFrame(
            left, fg_color="transparent",
            scrollbar_button_color=theme.BORDER,
            scrollbar_button_hover_color=theme.CARD_HOVER)
        self.list.pack(fill="both", expand=True, padx=8, pady=8)

        right = card(self)
        right.grid(row=0, column=1, padx=theme.PAGE_GAP,
                   pady=theme.PAGE_GAP, sticky="nsew")
        section_header(right, "UI & theme",
                       "Themes, backgrounds and recovery.", "EXPERIMENTAL",
                       padx=16, pady=(14, 4), wrap=320)
        q = ctk.CTkFrame(right, fg_color="transparent")
        q.pack(fill="x", padx=12, pady=(0, 4))
        for text, cmd, acc, level in [
                ("Apply Purple theme", lambda: self.apply_theme("Purple"),
                 True, "EXPERIMENTAL"),
                ("Apply Menu-only theme", lambda: self.apply_theme("Menu only"),
                 False, "EXPERIMENTAL"),
                ("Choose background", self.pick_background, False,
                 "EXPERIMENTAL"),
                ("Remove background", self.remove_background, False,
                 "EXPERIMENTAL"),
                ("Start UI with installed mods", self.start_ui, True,
                 "EXPERIMENTAL"),
                ("Revert to stock", self.revert, False, "RISKY")]:
            action_row(q, text, cmd, level, accent=acc, pady=2)
        helper_note(right,
                    "Mods are pushed to /vendor and loaded by n3mods.so at UI "
                    "start. Revert removes the theme/mod files; a reboot also "
                    "restores the stock UI.",
                    "EXPERIMENTAL", wraplength=280, padx=16, pady=(6, 12))

    def refresh(self):
        self.app.run_task(modman.refresh, "Refresh mods", on_done=self._render)

    def _render(self, rows, err):
        for w in self.list.winfo_children():
            w.destroy()
        if err:
            empty_state(self.list, "Could not load mods", str(err))
            return
        if not rows:
            empty_state(self.list, "No mods found",
                        "Add plugins under app/plugins/ or reinstall the "
                        "built-in mods.")
            return
        for m in rows:
            level = mod_safety_level(m)
            row = ctk.CTkFrame(self.list, fg_color=theme.CARD_ALT,
                               corner_radius=theme.RADIUS_CONTROL,
                               border_width=1, border_color=theme.BORDER_SOFT)
            row.pack(fill="x", pady=4, padx=2)
            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(side="left", fill="x", expand=True, padx=12, pady=10)
            head = ctk.CTkFrame(body, fg_color="transparent")
            head.pack(fill="x")
            lbl(head, m.get("name", m.get("id")), 13, True).pack(side="left")
            SafetyBadge(head, level, compact=True).pack(
                side="left", padx=(8, 0))
            inst = bool(m.get("installed"))
            if inst:
                state = ctk.CTkLabel(head, text="INSTALLED",
                                     font=theme.font(9, True),
                                     text_color=theme.SAFE,
                                     fg_color=theme.SAFE_BG,
                                     corner_radius=6, padx=6, height=18)
                state.pack(side="right")
            line = "%s · v%s · %s" % (m.get("type", "mod"),
                                      m.get("version", "?"),
                                      m.get("id", "?"))
            muted(body, line, 10).pack(anchor="w", pady=(2, 0))
            if m.get("notes"):
                muted(body, m["notes"], 10, wraplength=430,
                      justify="left").pack(anchor="w", pady=(2, 0))
            b = btn(row, "Remove" if inst else "Install",
                    lambda mid=m["id"], on=inst: self.toggle(mid, on),
                    accent=not inst)
            b.pack(side="right", padx=10)

    def toggle(self, mid, installed):
        rec = modman.find(mid) or {}
        level = mod_safety_level(rec)
        if not installed and level != "SAFE":
            if not messagebox.askyesno(
                    "Install %s mod" % level,
                    "%s is marked %s.\n\nInstall it anyway?\n\n"
                    "Recovery: use Revert to stock or Recover stock UI."
                    % (rec.get("name", mid), level)):
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
        if messagebox.askyesno("Revert to stock · RISKY",
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
        bar.grid(row=0, column=0, padx=theme.PAGE_GAP,
                 pady=theme.PAGE_GAP, sticky="ew")
        section_header(bar, "Logs", "Read-only tails from the goggles.",
                       "SAFE", padx=16, pady=(14, 4), wrap=520)
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))
        muted(row, "Tail last 200 lines", 10).pack(side="left")
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right")
        for name, path in [("natartos", "/data/local/tmp/natartos.log"),
                           ("n3mods", "/data/local/tmp/n3mods.log"),
                           ("dji_glasses", "/data/local/tmp/dji_glasses.log"),
                           ("texttint", "/data/local/tmp/n3_texttint.log")]:
            btn(btns, name, lambda p=path: self.tail(p),
                height=32).pack(side="left", padx=3)
        btn(btns, "Clear", self.clear, height=32).pack(side="left", padx=3)

        body = card(self)
        body.grid(row=1, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="nsew")
        section_header(body, "Output", "Monospace · scrollable", "SAFE",
                       padx=12, pady=(12, 4), wrap=520)
        self.text = log_textbox(body, height=300, size=11)
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.text.insert("end", "Select a log above to tail it.\n")
        self.text.configure(state="disabled")

    def append(self, text):
        self.text.configure(state="normal")
        self.text.insert("end", text + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "Select a log above to tail it.\n")
        self.text.configure(state="disabled")

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
        self.grid_rowconfigure(0, weight=1)
        page = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=theme.BORDER,
            scrollbar_button_hover_color=theme.CARD_HOVER)
        page.pack(fill="both", expand=True)

        info = card(page)
        info.pack(fill="x", padx=theme.PAGE_GAP, pady=theme.PAGE_GAP)
        section_header(info, "Paths", "Local folders used by the app", "SAFE",
                       padx=16, pady=(14, 4), wrap=760)
        for name, path in [("App", APP_DIR), ("Tools", n3ctl.TOOLS),
                           ("ADB", n3ctl.find_adb() or "not found"),
                           ("Stock lib", STOCK_LIB if os.path.exists(STOCK_LIB)
                            else "missing (theme building disabled)")]:
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            muted(row, name, 12).pack(side="left")
            lbl(row, path, 10, True, theme.MUTED, mono=True,
                wraplength=520, justify="right", anchor="e").pack(side="right")
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 14))
        btn(row, "Open app folder", lambda: self.open(APP_DIR)).pack(side="left")
        btn(row, "Open tools", lambda: self.open(n3ctl.TOOLS)).pack(
            side="left", padx=6)
        btn(row, "Open screenshots", lambda: self.open(SHOTS)).pack(side="left")

        opts = card(page)
        opts.pack(fill="x", padx=theme.PAGE_GAP, pady=theme.PAGE_GAP)
        section_header(opts, "Behaviour", "App-level preferences", "SAFE",
                       padx=16, pady=(14, 4), wrap=760)
        self.auto = tk.BooleanVar(value=True)
        self.restore = tk.BooleanVar(value=True)
        for title, detail, var in [
                ("Auto-refresh connection status",
                 "Check USB, root and ADB every 5 seconds.", self.auto),
                ("Restore stock USB when the app closes",
                 "Closes the root session and restores the USB composition.",
                 self.restore)]:
            row = ctk.CTkFrame(opts, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left")
            lbl(text, title, 12).pack(anchor="w")
            muted(text, detail, 10).pack(anchor="w")
            ctk.CTkSwitch(row, text="", variable=var,
                          progress_color=theme.ACCENT).pack(side="right")
        ctk.CTkLabel(opts, text="", height=8).pack()

        key = card(page)
        key.pack(fill="x", padx=theme.PAGE_GAP, pady=theme.PAGE_GAP)
        lbl(key, "DANGER - never write /system after disabling verity. "
                 "dm-verity mode 2 bricks the device on reboot and there is no "
                 "known unbrick. This app only writes /vendor and "
                 "/data/local/tmp.",
            11, True, theme.BAD, wraplength=760, justify="left").pack(
                anchor="w", padx=16, pady=(14, 4))
        section_header(key, "Safety key", "How to read every badge", "SAFE",
                       padx=16, pady=(6, 6), wrap=760)
        for level, text in [
                ("SAFE", "Read-only, or fully reversible without changes."),
                ("EXPERIMENTAL", "Restarts the UI or changes display output; recovery is available."),
                ("RISKY", "Root, vendor writes, recovery or radio probing. Review before use.")]:
            row = ctk.CTkFrame(key, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            SafetyBadge(row, level).pack(side="left", anchor="n")
            muted(row, text, 11, wraplength=660,
                  justify="left").pack(side="left", padx=(10, 0))
        ctk.CTkLabel(key, text="", height=8).pack()

        about = card(page)
        about.pack(fill="x", padx=theme.PAGE_GAP, pady=theme.PAGE_GAP)
        section_header(about, "N3 ROOT v%s" % VERSION,
                       "Session-only control deck for DJI Goggles N3.", "SAFE",
                       padx=16, pady=(14, 4), wrap=760)
        muted(about, "No /system, dm-verity, OTP/RPMB or bootloader changes. "
                     "Recover stock UI is always available.", 12,
              wraplength=760, justify="left").pack(
            anchor="w", padx=16, pady=(0, 14))

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
        head.grid(row=0, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="ew")
        section_header(head, "Sparrow2 — internal 5.8 GHz",
                       "Read-only research surface; no writes, no factory mode.",
                       "RISKY", padx=16, pady=(14, 4), wrap=760)
        muted(head, "Sparrow2 is DJI's radio SoC (USB product string C5, "
                    "2ca3:1020). ESP32-C5 is a different, unrelated chip.",
              11, wraplength=760, justify="left").pack(
            anchor="w", padx=16, pady=(0, 4))
        muted(head, "The AP has no IQ/ADC device. A shipped console exists "
                    "(/system/bin/sdr_shell), but the test:7 DUSS host is the "
                    "factory PC fixture. A factory-flag attempt did not register "
                    "it (queries return -1002/-1007). AP-side Sparrow2 channels "
                    "are logs/dumps only.", 11,
              wraplength=760, justify="left").pack(
            anchor="w", padx=16, pady=(0, 8))
        helper_note(head,
                    "All probes are read-only. No firmware, NVRAM or factory "
                    "state is written; a reboot recovers the normal radio mode.",
                    "SAFE", wraplength=760, padx=16, pady=(0, 14))

        acts = card(self)
        acts.grid(row=1, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="ew")
        self._group(acts, "Read-only diagnostics", "SAFE", [
            ("Firmware inventory", self.inventory),
            ("List Sparrow2 tools", self.tools),
            ("Sparrow2 summary", self.open_summary),
            ("Load findings", self.load_findings),
            ("Generate report", self.report),
            ("Radio probe doc", self.open_doc),
        ], cols=3)
        self._group(acts, "Radio query", "RISKY", [
            ("Console help (read-only)", self.console_help),
            ("Bulk console probe", self.bulk_probe),
        ], cols=2)
        helper_note(acts,
                    "Console help and the bulk probe send one read-only 'help' "
                    "query. No writes or factory mode; a reboot recovers the "
                    "normal state.",
                    "RISKY", wraplength=760, padx=16, pady=(0, 12))

        body = card(self)
        body.grid(row=2, column=0, padx=theme.PAGE_GAP,
                  pady=theme.PAGE_GAP, sticky="nsew")
        section_header(body, "Probe output", "Read-only · monospace", "SAFE",
                       padx=12, pady=(12, 4), wrap=760)
        self.text = log_textbox(body, height=120, size=11)
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.append("Select a probe. Nothing here writes to the goggles or "
                    "enters factory mode.\n")

    def _group(self, parent, title, level, items, cols=3):
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(10, 0))
        lbl(head, title, 12, True).pack(side="left")
        SafetyBadge(head, level).pack(side="left", padx=(8, 0))
        button_grid(parent, items, cols=cols, padx=12, pady=(2, 2),
                    height=32)

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
            confirm="RISKY — sends a read-only 'help' query to Sparrow2 "
                    "over /bulk/s2 using a custom DUSS route. Continue?")


class App(ctk.CTk):
    def __init__(self):
        theme.setup()
        super().__init__(fg_color=theme.BG)
        self.title("N3 ROOT — DJI Goggles N3")
        self.geometry("1280x820")
        self.minsize(1120, 720)
        self.grid_rowconfigure(1, weight=1)
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
        side = ctk.CTkFrame(self, width=238, corner_radius=0,
                            fg_color=theme.SIDEBAR)
        side.grid(row=0, column=0, rowspan=3, sticky="nsew")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(3, weight=1)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 18))
        mark = ctk.CTkFrame(brand, width=4, height=44,
                            fg_color=theme.ACCENT, corner_radius=2)
        mark.pack(side="left", padx=(0, 10))
        mark.pack_propagate(False)
        text = ctk.CTkFrame(brand, fg_color="transparent")
        text.pack(side="left")
        lbl(text, "N3 ROOT", 21, True, theme.ACCENT).pack(anchor="w")
        muted(text, "GOGGLES N3 · CONTROL DECK", 9).pack(anchor="w")

        sep = ctk.CTkFrame(side, height=1, fg_color=theme.BORDER_SOFT,
                           corner_radius=0)
        sep.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        nav = ctk.CTkFrame(side, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew")
        nav.grid_columnconfigure(0, weight=1)
        self.nav = {}
        self.nav_bars = {}
        groups = [
            ("DEVICE", [("connection", "Connection", "◈"),
                        ("goggles", "E42OZ", "◉"),
                        ("sparrow", "Sparrow2", "✦")]),
            ("SYSTEM", [("shell", "Root Shell", "▣"),
                        ("mods", "Mods & UI", "◆"),
                        ("logs", "Logs", "≡"),
                        ("settings", "Settings", "⚙")]),
        ]
        row = 0
        for group, items in groups:
            lbl(nav, group, 9, True, theme.DIM).grid(
                row=row, column=0, sticky="w", padx=24, pady=(10, 3))
            row += 1
            for key, text, icon in items:
                item = ctk.CTkFrame(nav, fg_color="transparent", height=40)
                item.grid(row=row, column=0, sticky="ew", padx=12, pady=2)
                item.grid_propagate(False)
                item.grid_columnconfigure(1, weight=1)
                bar = ctk.CTkFrame(item, width=3, height=20,
                                   fg_color="transparent", corner_radius=2)
                bar.grid(row=0, column=0, padx=(7, 0), pady=10)
                b = ctk.CTkButton(
                    item, text="  %s   %s" % (icon, text), anchor="w",
                    fg_color="transparent", hover_color=theme.CARD_HOVER,
                    text_color=theme.MUTED, font=theme.font(13),
                    corner_radius=9, height=38,
                    command=lambda k=key: self.show_page(k))
                b.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=1)
                self.nav[key] = b
                self.nav_bars[key] = bar
                row += 1

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        status = ctk.CTkFrame(footer, fg_color=theme.CARD, corner_radius=10,
                              border_width=1, border_color=theme.BORDER_SOFT)
        status.pack(fill="x")
        self.side_status = ctk.CTkLabel(status, text="●  disconnected",
                                        font=theme.font(11),
                                        text_color=theme.DIM)
        self.side_status.pack(anchor="w", padx=12, pady=(8, 1))
        muted(status, "USB · ROOT · ADB", 9).pack(anchor="w", padx=12,
                                                  pady=(0, 8))
        muted(footer, "v%s · experimental · session-only" % VERSION, 9).pack(
            anchor="w", pady=(8, 0))

    def _build_main(self):
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=1, sticky="ew", padx=18, pady=(14, 0))
        head.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(head, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor="w")
        self.page_title = lbl(title_row, "Connection", 22, True)
        self.page_title.pack(side="left")
        self.page_badge = SafetyBadge(title_row, "SAFE")
        self.page_badge.pack(side="left", padx=(10, 0))
        self.page_sub = muted(left, "", 11)
        self.page_sub.pack(anchor="w", pady=(2, 0))

        right = ctk.CTkFrame(head, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        self.pill_adb = pill(right, "ADB —")
        self.pill_adb.pack(side="left", padx=4)
        self.pill_root = pill(right, "ROOT —")
        self.pill_root.pack(side="left", padx=4)
        self.pill_ui = pill(right, "UI —")
        self.pill_ui.pack(side="left", padx=4)
        btn(right, "Refresh", self.refresh_status).pack(side="left",
                                                       padx=(10, 0))

        div = ctk.CTkFrame(head, height=1, fg_color=theme.BORDER_SOFT,
                           corner_radius=0)
        div.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        self.host = ctk.CTkFrame(self, fg_color="transparent")
        self.host.grid(row=1, column=1, sticky="nsew", padx=18, pady=12)
        self.host.grid_rowconfigure(0, weight=1)
        self.host.grid_columnconfigure(0, weight=1)

        status = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, corner_radius=0,
                              height=28)
        status.grid(row=2, column=1, sticky="ew")
        status.grid_propagate(False)
        status.grid_columnconfigure(0, weight=1)
        self.statusbar = lbl(status, "Ready.", 11, False, theme.MUTED,
                             anchor="w")
        self.statusbar.grid(row=0, column=0, sticky="w", padx=18)
        lbl(status, "session-only · no persistent changes", 9, False,
            theme.DIM).grid(row=0, column=1, sticky="e", padx=18)

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
            active = k == key
            b.configure(fg_color=theme.CARD if active else "transparent",
                        text_color=theme.ACCENT if active else theme.MUTED)
            self.nav_bars[k].configure(
                fg_color=theme.ACCENT if active else "transparent")
        title, subtitle, level = PAGE_META[key]
        self.page_title.configure(text=title)
        self.page_sub.configure(text=subtitle)
        self.page_badge.set_level(level)
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
            text_color=theme.SAFE if (adb_on or root_on) else theme.DIM)
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
                "Apply theme · EXPERIMENTAL",
                "Build and install the '%s' theme?\n"
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
