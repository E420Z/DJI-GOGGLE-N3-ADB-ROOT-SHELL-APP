"""Reusable controls and layout helpers for the N3 ROOT UI.

Keeping these in one place gives every page the same spacing, button heights,
card styling and safety vocabulary.
"""
from __future__ import annotations

import customtkinter as ctk

from . import theme

SAFETY_LEVELS = ("SAFE", "EXPERIMENTAL", "RISKY")

_LEVEL_ALIASES = {
    "SAFE": "SAFE",
    "LOW": "SAFE",
    "OK": "SAFE",
    "STABLE": "SAFE",
    "EXPERIMENTAL": "EXPERIMENTAL",
    "MEDIUM": "EXPERIMENTAL",
    "WARN": "EXPERIMENTAL",
    "PREVIEW": "EXPERIMENTAL",
    "RISKY": "RISKY",
    "HIGH": "RISKY",
    "BAD": "RISKY",
    "CRITICAL": "RISKY",
}


def normalize_level(level: str = "EXPERIMENTAL") -> str:
    """Return one of SAFE / EXPERIMENTAL / RISKY."""
    key = str(level or "EXPERIMENTAL").strip().upper().replace("-", "_")
    return _LEVEL_ALIASES.get(key, "EXPERIMENTAL")


class SafetyBadge(ctk.CTkLabel):
    """Small colour-coded badge using the app-wide safety vocabulary."""

    def __init__(self, parent, level: str = "EXPERIMENTAL", *,
                 compact: bool = False, **kwargs):
        self.level = normalize_level(level)
        self.compact = compact
        kwargs.setdefault("height", 20 if compact else 22)
        kwargs.setdefault("corner_radius", 7)
        kwargs.setdefault("padx", 7 if compact else 8)
        super().__init__(
            parent,
            text=self._badge_text(),
            font=theme.font(9 if compact else 10, True),
            text_color=theme.safety_color(self.level),
            fg_color=theme.safety_bg(self.level),
            **kwargs,
        )

    def _badge_text(self) -> str:
        return self.level if self.compact else "●  " + self.level

    def set_level(self, level: str) -> None:
        self.level = normalize_level(level)
        self.configure(text=self._badge_text(),
                       text_color=theme.safety_color(self.level),
                       fg_color=theme.safety_bg(self.level))


def safety_badge(parent, level: str = "EXPERIMENTAL", **kwargs) -> SafetyBadge:
    return SafetyBadge(parent, level, **kwargs)


# ------------------------------------------------------------------ surfaces
def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=theme.CARD,
                        corner_radius=theme.RADIUS_CARD,
                        border_width=1, border_color=theme.BORDER, **kw)


def lbl(parent, text, size=13, bold=False, color=theme.TEXT, mono=False, **kw):
    return ctk.CTkLabel(parent, text=text,
                        font=theme.font(size, bold, mono),
                        text_color=color, **kw)


def muted(parent, text, size=12, **kw):
    return ctk.CTkLabel(parent, text=text, font=theme.font(size),
                        text_color=theme.MUTED, **kw)


def pill(parent, text):
    return ctk.CTkLabel(parent, text=text, font=theme.font(10, True),
                        fg_color=theme.CARD_ALT, text_color=theme.MUTED,
                        corner_radius=7, padx=9, height=24)


def set_pill(p, on, on_text, off_text):
    """Tinted header pill (connection state)."""
    p.configure(text=on_text if on else off_text,
                fg_color=theme.SAFE_BG if on else theme.CARD_ALT,
                text_color=theme.SAFE if on else theme.MUTED)


def set_tile(p, on, on_text, off_text):
    """Large read-only status value (connection page tiles)."""
    p.configure(text=on_text if on else off_text,
                fg_color="transparent",
                text_color=theme.SAFE if on else theme.DIM)


# ------------------------------------------------------------------- controls
def btn(parent, text, command, accent=False, **kw):
    kw.setdefault("height", theme.BTN_HEIGHT)
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=theme.ACCENT if accent else theme.CARD_ALT,
        hover_color=theme.ACCENT_HOVER if accent else theme.CARD_HOVER,
        text_color="#0B0710" if accent else theme.TEXT,
        text_color_disabled=theme.DIM,
        font=theme.font(12, bool(accent)),
        corner_radius=theme.RADIUS_CONTROL,
        border_width=0, **kw)


def action_row(parent, text, command, level: str | None = None, *,
               accent: bool = False, height: int = 34, pady: int = 3):
    """A full-width action button with its safety level on the right."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=pady)
    b = btn(row, text, command, accent=accent, height=height)
    b.pack(side="left", fill="x", expand=True)
    if level:
        SafetyBadge(row, level, compact=True).pack(side="right", padx=(8, 0))
    return b


def action_cell(parent, text, command, level: str | None = None, *,
                accent: bool = False, height: int = 34):
    """Compact grid cell: button with its safety level underneath."""
    cell = ctk.CTkFrame(parent, fg_color="transparent")
    btn(cell, text, command, accent=accent, height=height).pack(fill="x")
    if level:
        SafetyBadge(cell, level, compact=True).pack(anchor="w", pady=(3, 0))
    return cell


def button_grid(parent, items, cols: int = 3, *, padx: int = 12,
                pady: int = (0, 8), height: int | None = None):
    """items: sequence of (text, command) or (text, command, accent)."""
    grid = ctk.CTkFrame(parent, fg_color="transparent")
    grid.pack(fill="x", padx=padx, pady=pady)
    for c in range(cols):
        grid.grid_columnconfigure(c, weight=1)
    for i, item in enumerate(items):
        text, command = item[0], item[1]
        accent = bool(item[2]) if len(item) > 2 else False
        extra = {"height": height} if height else {}
        b = btn(grid, text, command, accent=accent, **extra)
        b.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="ew")
    return grid


# ------------------------------------------------------------------ structure
def section_header(parent, title, subtitle=None, level=None, *,
                   padx=theme.CARD_PAD, pady=(14, 6), size=15, wrap=620,
                   anchor_title=True):
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", padx=padx, pady=pady)
    top = ctk.CTkFrame(box, fg_color="transparent")
    top.pack(fill="x")
    lbl(top, title, size, True).pack(side="left" if anchor_title else "top")
    if level:
        SafetyBadge(top, level).pack(side="left" if anchor_title else "top",
                                      padx=(8, 0) if anchor_title else (0, 4))
    if subtitle:
        muted(box, subtitle, 11, wraplength=wrap, justify="left",
              anchor="w").pack(fill="x", pady=(3, 0))
    return box


def helper_note(parent, text, level=None, *, wraplength=620,
                padx=theme.CARD_PAD, pady=(0, 12)):
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", padx=padx, pady=pady)
    if level:
        SafetyBadge(box, level).pack(side="left", anchor="n", padx=(0, 8))
    lbl(box, text, 10, False, theme.MUTED, wraplength=wraplength,
        justify="left", anchor="w").pack(side="left", fill="x", expand=True)
    return box


def status_row(parent, name, value="—", *, padx=theme.CARD_PAD,
               value_size=12, value_color=theme.TEXT):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=padx, pady=3)
    muted(row, name, 12).pack(side="left")
    v = lbl(row, value, value_size, True, value_color)
    v.pack(side="right")
    return v


def separator(parent, *, padx=theme.CARD_PAD, pady=theme.SECTION_GAP):
    f = ctk.CTkFrame(parent, height=1, fg_color=theme.BORDER_SOFT,
                     corner_radius=0)
    f.pack(fill="x", padx=padx, pady=pady)
    return f


def empty_state(parent, title, body="", *, pady=24):
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="both", expand=True, padx=20, pady=pady)
    lbl(box, title, 13, True, theme.MUTED).pack(pady=(8, 2))
    if body:
        muted(box, body, 11, wraplength=420, justify="center").pack()
    return box


def log_textbox(parent, *, height=140, size=11, wrap="none", **kw):
    return ctk.CTkTextbox(
        parent, fg_color=theme.CONSOLE, border_width=1,
        border_color=theme.BORDER, corner_radius=theme.RADIUS_CONTROL,
        scrollbar_button_color=theme.BORDER,
        scrollbar_button_hover_color=theme.CARD_HOVER,
        font=theme.font(size, mono=True), text_color=theme.TEXT_SOFT,
        wrap=wrap, **kw)
