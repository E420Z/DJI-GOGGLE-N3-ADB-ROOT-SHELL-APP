"""Shared look-and-feel for the N3 ROOT app."""
from __future__ import annotations

import customtkinter as ctk

BG = "#0B0910"
SIDEBAR = "#100C17"
CARD = "#181222"
CARD_HOVER = "#211A2E"
CARD_ALT = "#1F1730"
BORDER = "#2B2038"
ACCENT = "#B44BFF"
ACCENT_HOVER = "#C976FF"
ACCENT_DARK = "#7A2BE0"
TEXT = "#F5F1FF"
MUTED = "#9B8FB5"
DIM = "#6E6480"
OK = "#4ADE80"
WARN = "#FBBF24"
BAD = "#F87171"
BLUE = "#60A5FA"

FONT = "Segoe UI"
FONT_MONO = "Cascadia Mono"


def setup() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def font(size: int = 13, bold: bool = False, mono: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_MONO if mono else FONT,
                       size=size, weight="bold" if bold else "normal")
