"""Shared look-and-feel for the N3 ROOT app."""
from __future__ import annotations

import customtkinter as ctk

# ------------------------------------------------------------------ surfaces
BG = "#0B0910"
SIDEBAR = "#100C17"
CARD = "#181222"
CARD_HOVER = "#211A2E"
CARD_ALT = "#1F1730"
BORDER = "#2B2038"
BORDER_SOFT = "#241C32"
CONSOLE = "#07050C"

# ------------------------------------------------------------------- accents
ACCENT = "#B44BFF"
ACCENT_HOVER = "#C976FF"
ACCENT_DARK = "#7A2BE0"

# ---------------------------------------------------------------------- text
TEXT = "#F5F1FF"
TEXT_SOFT = "#D8D2E8"
MUTED = "#9B8FB5"
DIM = "#6E6480"

# ------------------------------------------------------------ semantic hues
OK = "#4ADE80"
WARN = "#FBBF24"
BAD = "#F87171"
BLUE = "#60A5FA"

# ------------------------------------------------------------- safety levels
# Exactly three user-facing levels. Keep wording and colours identical
# everywhere so a badge always means the same thing.
SAFE = "#4ADE80"
SAFE_BG = "#11261A"
EXPERIMENTAL = "#FBBF24"
EXPERIMENTAL_BG = "#2A2213"
RISKY = "#F87171"
RISKY_BG = "#2A151A"

_SAFETY_COLORS = {
    "SAFE": (SAFE, SAFE_BG),
    "EXPERIMENTAL": (EXPERIMENTAL, EXPERIMENTAL_BG),
    "RISKY": (RISKY, RISKY_BG),
}


def safety_color(level: str) -> str:
    return _SAFETY_COLORS.get(str(level).upper(), (WARN, EXPERIMENTAL_BG))[0]


def safety_bg(level: str) -> str:
    return _SAFETY_COLORS.get(str(level).upper(), (WARN, EXPERIMENTAL_BG))[1]


# ------------------------------------------------------------------- layout
PAGE_GAP = 6
CARD_PAD = 16
SECTION_GAP = 8
RADIUS_CARD = 14
RADIUS_CONTROL = 10
BTN_HEIGHT = 36

FONT = "Segoe UI"
FONT_MONO = "Cascadia Mono"


def setup() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def font(size: int = 13, bold: bool = False, mono: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_MONO if mono else FONT,
                       size=size, weight="bold" if bold else "normal")
