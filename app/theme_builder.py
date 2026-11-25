"""theme_builder.py - build a custom N3 UI theme from the stock libew_gls.so.

Patches:
  * OSD/widget text literal + the two text-init call sites
  * app-init text literal + the white SetColor call sites
  * the DuThemedControls*Color palette globals (RGBA bytes), including
    HighlightBorderColor (focus box) and HighlightTextColor
  * every gold movz/movk pair in .text (41 sites) - focus rings, selected
    icons and selected labels
  * the DuTheme / MxComponent text getters (32-bit RGBA)

The original gold scanner used the wrong opcode mask (0x5299FE00 instead of
0x52999FE0) and matched zero sites; see _find_gold_pairs().

Icons and the focus box are multi-frame bitmap assets, so they are not fully
covered by these static patches.  The runtime n3_bitmap.so hook recolours
those (native ARGB and Index8).  See notes/UI_RENDERING_ARCHITECTURE.md.
"""
from __future__ import annotations

import hashlib
import os
import struct

# --- stock libew_gls.so addresses (N3 fw 10.00.59.41) ----------------------
LIT_OSD = 0x60D0AB8          # loaded by DuThemedControlsText__Init
LIT_APP = 0x6167238          # app-init literal, reused for the menu label colour
TEXT_INIT = (0x60D0A80, 0x60CC2A0)
SETTER = 0x6179960           # MxBindableLabel__OnSetColor

# Main-menu labels use ViewsText_OnSetColor (0x61792d0) with hardcoded
# white/gold/grey values, so they need their own sites.
MENU_TEXT_SITES = (
    # IconText / base menu
    0x60CB268, 0x60CB320, 0x60CC9C4,
    # Label / SubMenu / Switch / Selector / list rows
    0x60C9DB0, 0x60CA4B4, 0x60C9724, 0x60C9B78, 0x60C9FA8,
    0x60CA1F8, 0x60CA6E4, 0x60CB484, 0x60CB644, 0x60CCBA0,
    0x60CCEF0,
)

# Every white ViewsText_OnSetColor site found in the settings/menu classes
# (Camera/Display/Status/Transmission, RC, gallery, dialogs, ...).  The builder
# patches the ones that have a literal in +-1 MB and logs the rest.
UI_TEXT_SITES = (
    0x5FACF40, 0x5FACFA0, 0x5FC1018, 0x5FD5C9C, 0x5FD8A64, 0x5FD99D4,
    0x5FD9E14, 0x5FDABB8, 0x5FE8AC8, 0x5FE8B10, 0x5FE8B64, 0x5FEC668,
    0x60460D8, 0x604612C, 0x60461C0, 0x6064470, 0x6064AAC, 0x60677BC,
    0x606822C, 0x606872C, 0x6068C48, 0x6069170, 0x60696A0, 0x6069E70,
    0x60A4378, 0x60A43FC, 0x60A92C8, 0x60A9310, 0x60A9364, 0x60AA688,
    0x60B2138, 0x60BC150, 0x60BC20C, 0x60C9720, 0x60C9B74, 0x60C9DB0,
    0x60C9FA4, 0x60CA1F4, 0x60CA4B4, 0x60CA6E0, 0x60CA7C0, 0x60CB268,
    0x60CB480, 0x60CB640, 0x60CB81C, 0x60CB8AC, 0x60CBE4C, 0x60CC5F4,
    0x60CC6CC, 0x60CC9C4, 0x60CCB9C, 0x60CCCFC, 0x60CCDF0, 0x60CD3D8,
    0x60CD56C, 0x60CD72C, 0x60CDFF8, 0x60CE614, 0x60CE9A8, 0x60CF324,
    0x60CF968, 0x60D0660, 0x60D06E4, 0x60D2E84, 0x60D305C, 0x60D3174,
    0x60D334C, 0x60D3494, 0x60D3D64, 0x60D3ED0, 0x60D41D0, 0x60D5478,
    0x60D551C, 0x60D574C, 0x60D5758, 0x60D5E5C, 0x60D797C, 0x60D7A50,
    0x60D7E20, 0x60D7FB8, 0x60D9158, 0x60D9840, 0x60F06D4, 0x60F0784,
    0x60F08D0, 0x60F21D0, 0x60F223C, 0x60F2618, 0x611A658, 0x6124E00,
    0x6125058, 0x6125324, 0x612539C, 0x6147DEC,
)
# `mov w8, #-1` in the UpdateViewState functions (w1 is selected later by csel)
MENU_STATE_WHITE_SITES = (0x60C9E8C, 0x60CA5DC)
# (movz site, movk site); some pairs have an `add x0` between them.
MENU_ACTIVE_PAIRS = (
    (0x60CB348, 0x60CB34C),   # IconText selected text
    (0x60CB208, 0x60CB210),   # IconText focus border
    (0x60C9D6C, 0x60C9D74),   # LabelMenuItem border
    (0x60CA470, 0x60CA478),   # SubMenuMenuItem border
)
MENU_DISABLED_PAIRS = (
    (0x60CB334, 0x60CB338),   # IconText
    (0x60C9E78, 0x60C9E84),   # LabelMenuItem
    (0x60CA5C8, 0x60CA5D4),   # SubMenuMenuItem
    (0x60C9C98, 0x60C9CA4),   # SwitchMenuItem
)

GLOBALS = {
    "plain": 0x1F4B7D9,       # DuThemedControlsPlainTextColor
    "active": 0x1F4B7F8,      # DuThemedControlsActiveTextColor (stock gold)
    "highlight": 0x1F4B800,   # DuThemedControlsHighlightTextColor
    "border": 0x1F4B81C,      # DuThemedControlsHighlightBorderColor (focus box, stock gold)
    "disabled": 0x1F4B820,    # DuThemedControlsDisabledTextColor
    "link": 0x1F4BB74,        # DuThemedControlsHyperLinkTextColor
    "normal": 0x1F4C8E4,      # DuThemedControlsNormalCellColor
}

GETTERS = {
    "du": [(0x60C9640, 0x10), (0x60C9650, 0x10),
           (0x60C9660, 0x10), (0x60C9670, 0x10)],
    "mx": [(0x6141030, 0x30), (0x6141060, 0x34),
           (0x61410A0, 0x30), (0x61410D0, 0x34)],
}

ELEMENTS = [
    ("osd", "OSD / widget text", "Text drawn over the video and value widgets."),
    ("plain", "Plain text", "Normal labels and list text."),
    ("highlight", "Highlight text", "Highlighted list text."),
    ("normal", "Normal cell", "Cell/value text."),
    ("active", "Active / selected", "Selected menu text (stock gold)."),
    ("border", "Focus border", "Selected item focus box outline and selected icon (stock gold)."),
    ("link", "Hyperlink / accent", "Links and accent text."),
    ("disabled", "Disabled text", "Greyed-out text."),
    ("app", "Menu label text", "Unselected menu labels (left and right menus)."),
    ("menu_active", "Menu selected", "Selected menu label and focus border."),
    ("menu_disabled", "Menu disabled", "Disabled menu labels."),
    ("menu_focus", "Menu focus / gold", "ActiveTextColor used by other pages and the selected icon."),
    ("du", "Dialog / DuTheme text", "Dialog and theme text (experimental)."),
    ("mx", "Component text", "MxComponent text (experimental)."),
]

PRESETS = {
    "Purple": {
        "osd": "#C084FC", "app": "#C084FC", "plain": "#E9D5FF",
        "highlight": "#D8B4FE", "normal": "#C084FC", "active": "#A855F7",
        "link": "#A855F7", "disabled": "#7E5A9E", "du": "#C084FC",
        "mx": "#C084FC",
    },
    "Cyan": {
        "osd": "#67E8F9", "app": "#67E8F9", "plain": "#CFFAFE",
        "highlight": "#A5F3FC", "normal": "#67E8F9", "active": "#22D3EE",
        "link": "#22D3EE", "disabled": "#4B7C86", "du": "#67E8F9",
        "mx": "#67E8F9",
    },
    "Green": {
        "osd": "#86EFAC", "app": "#86EFAC", "plain": "#DCFCE7",
        "highlight": "#BBF7D0", "normal": "#86EFAC", "active": "#4ADE80",
        "link": "#4ADE80", "disabled": "#4D7C5B", "du": "#86EFAC",
        "mx": "#86EFAC",
    },
    "Amber": {
        "osd": "#FCD34D", "app": "#FCD34D", "plain": "#FEF3C7",
        "highlight": "#FDE68A", "normal": "#FCD34D", "active": "#F59E0B",
        "link": "#F59E0B", "disabled": "#8A6A2F", "du": "#FCD34D",
        "mx": "#FCD34D",
    },
    "Red": {
        "osd": "#FCA5A5", "app": "#FCA5A5", "plain": "#FEE2E2",
        "highlight": "#FECACA", "normal": "#FCA5A5", "active": "#EF4444",
        "link": "#EF4444", "disabled": "#8A4A4A", "du": "#FCA5A5",
        "mx": "#FCA5A5",
    },
}

for _cols in PRESETS.values():
    _cols.setdefault("menu_active", _cols["active"])
    _cols.setdefault("menu_disabled", _cols["disabled"])
    _cols.setdefault("menu_focus", _cols["active"])
    _cols.setdefault("border", _cols["active"])

PRESETS["Menu only"] = dict(PRESETS["Purple"])
PRESETS["Menu only"].update({
    "app": "#C084FC",
    "plain": "#C084FC",
    "highlight": "#C084FC",
    "menu_active": "#A855F7",
    "menu_disabled": "#7E5A9E",
    "menu_focus": "#A855F7",
    "border": "#A855F7",
    "link": "#A855F7",
    "disabled": "#7E5A9E",
})

PRESET_ENABLED = {
    name: {k: True for k, _, _ in ELEMENTS} for name in PRESETS
}
# Menu only keeps the OSD/palette globals out, but now also patches the named
# theme colours used by settings pages, the focus box and the icons:
# PlainTextColor (white), HighlightTextColor (white), ActiveTextColor (gold),
# HighlightBorderColor (gold) and the disabled/hyperlink colours.
PRESET_ENABLED["Menu only"] = {
    k: k in ("app", "plain", "highlight", "menu_active", "menu_disabled",
             "menu_focus", "border", "link", "disabled")
    for k, _, _ in ELEMENTS
}

DEFAULT_COLORS = dict(PRESETS["Purple"])
DEFAULT_ENABLED = {k: True for k, _, _ in ELEMENTS}


def _rgb(hex_color: str):
    s = hex_color.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError("colour must be #RRGGBB: %r" % hex_color)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _argb32(hex_color: str) -> int:
    r, g, b = _rgb(hex_color)
    return 0xFF000000 | (r << 16) | (g << 8) | b


def _rgba_bytes(hex_color: str) -> bytes:
    r, g, b = _rgb(hex_color)
    return bytes((r, g, b, 0xFF))


def _rgba32(hex_color: str) -> int:
    r, g, b = _rgb(hex_color)
    return (r << 24) | (g << 16) | (b << 8) | 0xFF


class ELF:
    """Tiny ELF64 reader: PT_LOAD mapping and .text lookup."""

    def __init__(self, data: bytes):
        if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
            raise ValueError("not a little-endian ELF64")
        self.data = data
        (self.e_phoff, self.e_shoff) = struct.unpack_from("<QQ", data, 0x20)
        self.e_phentsize, self.e_phnum = struct.unpack_from("<HH", data, 0x36)
        (self.e_shentsize, self.e_shnum,
         self.e_shstrndx) = struct.unpack_from("<HHH", data, 0x3A)
        self.loads = []
        for i in range(self.e_phnum):
            o = self.e_phoff + i * self.e_phentsize
            p_type, p_flags, p_offset, p_vaddr, _, p_filesz, _, _ = \
                struct.unpack_from("<IIQQQQQQ", data, o)
            if p_type == 1:  # PT_LOAD
                self.loads.append((p_vaddr, p_offset, p_filesz, p_flags))

    def va2off(self, va: int):
        for vaddr, offset, filesz, _flags in self.loads:
            if vaddr <= va < vaddr + filesz:
                return offset + (va - vaddr)
        return None

    def section(self, name: str):
        shstr = None
        if self.e_shnum:
            o = self.e_shoff + self.e_shstrndx * self.e_shentsize
            _, _, _, _, sh_offset, sh_size, _, _, _, _ = \
                struct.unpack_from("<IIQQQQIIQQ", self.data, o)
            shstr = self.data[sh_offset:sh_offset + sh_size]
        for i in range(self.e_shnum):
            o = self.e_shoff + i * self.e_shentsize
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
             sh_link, sh_info, sh_addralign, sh_entsize) = \
                struct.unpack_from("<IIQQQQIIQQ", self.data, o)
            if shstr is None:
                continue
            end = shstr.find(b"\x00", sh_name)
            if end < 0:
                continue
            if shstr[sh_name:end].decode("latin1") == name:
                return {
                    "addr": sh_addr, "offset": sh_offset, "size": sh_size,
                    "flags": sh_flags, "type": sh_type,
                }
        return None


def _ldr_w(rt: int, pc: int, target: int) -> bytes:
    delta = target - pc
    if delta % 4:
        raise ValueError("unaligned literal")
    imm19 = delta // 4
    if not (-(1 << 18) <= imm19 < (1 << 18)):
        raise ValueError("literal out of range")
    return (0x18000000 | ((imm19 & 0x7FFFF) << 5) | rt).to_bytes(4, "little")


def _movz_movk_ret(value: int) -> bytes:
    low = value & 0xFFFF
    high = (value >> 16) & 0xFFFF
    movz = 0x52800000 | (low << 5)       # movz w0, #low
    movk = 0x72A00000 | (high << 5)      # movk w0, #high, lsl 16
    return struct.pack("<III", movz, movk, 0xD65F03C0)


def _rgba_imm(hex_color: str) -> int:
    """32-bit immediate whose little-endian bytes are R,G,B,A."""
    r, g, b = _rgb(hex_color)
    return (0xFF << 24) | (b << 16) | (g << 8) | r


def _movz_movk_w1(value: int) -> bytes:
    return _movz_movk_reg(1, value)


def _movz_movk_reg(rd: int, value: int) -> bytes:
    low = value & 0xFFFF
    high = (value >> 16) & 0xFFFF
    movz = 0x52800000 | (low << 5) | (rd & 0x1F)
    movk = 0x72A00000 | (high << 5) | (rd & 0x1F)
    return struct.pack("<II", movz, movk)


def _find_gold_pairs(data: bytes, text):
    """Find movz wN,#0xccff + movk wN,#0xff00 pairs (gold)."""
    tva = text["addr"]
    tbuf = data[text["offset"]:text["offset"] + text["size"]]
    out = []
    for i in range(0, len(tbuf) - 4, 4):
        word = struct.unpack_from("<I", tbuf, i)[0]
        # movz wN, #0xccff  ->  0x52999FE0 | Rd
        if (word & 0xFFFFFFE0) != 0x52999FE0:
            continue
        rd = word & 0x1F
        for j in range(i + 4, min(i + 17, len(tbuf) - 4), 4):
            word2 = struct.unpack_from("<I", tbuf, j)[0]
            if (word2 & 0xFFFFFFE0) == 0x72BFE000 and (word2 & 0x1F) == rd:
                out.append((tva + i, tva + j, rd))
                break
    return out


def _find_white_sites(data: bytes, text):
    tva = text["addr"]
    tbuf = data[text["offset"]:text["offset"] + text["size"]]
    sites = []
    for pat, rt in ((b"\x01\x00\x80\x12", 1), (b"\x02\x00\x80\x12", 2)):
        start = 0
        while True:
            i = tbuf.find(pat, start)
            if i < 0:
                break
            start = i + 4
            va = tva + i
            found = None
            for j in range(i + 4, min(i + 36, len(tbuf) - 4), 4):
                raw = struct.unpack_from("<I", tbuf, j)[0]
                if (raw & 0xFC000000) != 0x94000000:
                    continue
                imm = raw & 0x03FFFFFF
                if imm & 0x02000000:
                    imm -= 0x04000000
                if (tva + j) + (imm << 2) == SETTER:
                    found = rt
                    break
            if found:
                sites.append((va, found))
    # de-duplicate (a site can be matched by both patterns only in theory)
    out = []
    seen = set()
    for va, rt in sites:
        if va in seen:
            continue
        seen.add(va)
        out.append((va, rt))
    return out


def build(colors: dict, enabled: dict, stock_lib: str, out_lib: str,
          log=print) -> str:
    data = bytearray(open(stock_lib, "rb").read())
    elf = ELF(data)
    text = elf.section(".text")
    if text is None:
        raise RuntimeError("no .text section in stock lib")

    def put(va, blob):
        off = elf.va2off(va)
        if off is None:
            raise RuntimeError("VA %#x is not mapped" % va)
        data[off:off + len(blob)] = blob

    patched = []

    if enabled.get("osd"):
        put(LIT_OSD, struct.pack("<I", _argb32(colors["osd"])))
        for va in TEXT_INIT:
            put(va, _ldr_w(1, va, LIT_OSD))
        patched.append("osd")

    def normalise_site(va, rt):
        """Accept either the mov wN,#-1 site or its following bl site."""
        off = elf.va2off(va)
        if off is None or off < 4:
            return None
        word = struct.unpack_from("<I", data, off)[0]
        if word == (0x12800000 | rt):
            return va
        if (word & 0xFC000000) == 0x94000000:
            prev = struct.unpack_from("<I", data, off - 4)[0]
            if prev == (0x12800000 | rt):
                return va - 4
        return None

    if enabled.get("app"):
        # ViewsText_OnSetColor expects RGBA bytes, so the literal is written as
        # RGBA and the menu label call sites load it directly.
        put(LIT_APP, _rgba_bytes(colors["app"]))
        skipped = []
        osd_lit_used = False
        for va in sorted(set(MENU_TEXT_SITES) | set(UI_TEXT_SITES)):
            target = normalise_site(va, 1)
            if target is None:
                skipped.append(va)
                continue
            if abs(target - LIT_APP) <= 0xFFFFF:
                lit = LIT_APP
            elif abs(target - LIT_OSD) <= 0xFFFFF:
                lit = LIT_OSD
                osd_lit_used = True
            else:
                skipped.append(va)
                continue
            put(target, _ldr_w(1, target, lit))
        for va in MENU_STATE_WHITE_SITES:
            target = normalise_site(va, 8)
            if target is None:
                skipped.append(va)
                continue
            put(target, _ldr_w(8, target, LIT_APP))
        if osd_lit_used:
            # LIT_OSD is only a literal slot; the stock OSD code does not load
            # it unless the OSD patch is enabled.  Reuse it for early menu text.
            put(LIT_OSD, _rgba_bytes(colors["app"]))
        if skipped:
            log("menu text sites skipped (out of range/no mov): " +
                ", ".join("%#x" % x for x in skipped))
        patched.append("menu text")

    if enabled.get("menu_active"):
        value = _rgba_imm(colors["menu_active"])
        for movz_va, movk_va in MENU_ACTIVE_PAIRS:
            blob = _movz_movk_reg(
                struct.unpack_from("<I", data, elf.va2off(movz_va))[0] & 0x1F,
                value)
            put(movz_va, blob[:4])
            put(movk_va, blob[4:])
        gold = _find_gold_pairs(data, text)
        for movz_va, movk_va, rd in gold:
            blob = _movz_movk_reg(rd, value)
            put(movz_va, blob[:4])
            put(movk_va, blob[4:])
        if gold:
            log("gold pairs patched: %d" % len(gold))
        # These two are the sidebar focus box and the selected menu icon.
        # They may already have been patched by MENU_ACTIVE_PAIRS, so check the
        # final bytes rather than membership in the scanner result.
        for va in (0x60D0DFC, 0x60CB208):
            off = elf.va2off(va)
            if off is not None:
                word = struct.unpack_from("<I", data, off)[0]
                if (word & 0xFFFFFFE0) == 0x52999FE0:
                    log("WARNING: gold site %#x still stock" % va)
        patched.append("menu active")

    if enabled.get("menu_disabled"):
        blob = _movz_movk_w1(_rgba_imm(colors["menu_disabled"]))
        for movz_va, movk_va in MENU_DISABLED_PAIRS:
            put(movz_va, blob[:4])
            put(movk_va, blob[4:])
        patched.append("menu disabled")

    for key, va in GLOBALS.items():
        if enabled.get(key):
            put(va, _rgba_bytes(colors[key]))
            patched.append(key)

    if enabled.get("menu_focus"):
        # Same ActiveTextColor global, but independent of the OSD/palette
        # toggles.  Other pages' focus/gold colour and the selected icon tint
        # use this global.
        put(GLOBALS["active"], _rgba_bytes(colors["menu_focus"]))
        patched.append("menu focus")

    for key, funcs in GETTERS.items():
        if enabled.get(key):
            code = _rgba32(colors[key])
            for va, size in funcs:
                blob = _movz_movk_ret(code)
                if len(blob) > size:
                    raise RuntimeError("getter %#x too small" % va)
                blob += b"\x1f\x20\x03\xd5" * ((size - len(blob)) // 4)
                put(va, blob)
            patched.append(key)

    # MxBindableLabel white SetColor sites: only when the OSD path is enabled.
    site_count = 0
    site_total = 0
    if enabled.get("osd"):
        sites = _find_white_sites(data, text)
        site_total = len(sites)
        for va, rt in sites:
            chosen = None
            for lit, key in ((LIT_OSD, "osd"), (LIT_APP, "app")):
                if enabled.get(key) and abs(va - lit) <= 0xFFFFF:
                    chosen = (lit, key)
                    break
            if not chosen:
                continue
            lit, _key = chosen
            put(va, _ldr_w(rt, va, lit))
            site_count += 1

    open(out_lib, "wb").write(data)
    digest = hashlib.sha256(data).hexdigest()
    log("theme built: %s (%d bytes, sha256 %s...)" %
        (out_lib, len(data), digest[:12]))
    log("patched: %s; white sites: %d of %d" %
        (", ".join(patched) or "none", site_count, site_total))
    return out_lib


def find_stock_lib(app_dir: str):
    candidates = [
        os.path.join(app_dir, "assets", "libew_gls_stock.so"),
        os.path.join(app_dir, "..", "..", "re", "ota_live", "lib64",
                     "libew_gls.so"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", default=None)
    ap.add_argument("--out", default="theme_test.so")
    ap.add_argument("--preset", default="Purple")
    args = ap.parse_args()
    app = os.path.dirname(os.path.abspath(__file__))
    stock = args.stock or find_stock_lib(app)
    if not stock:
        raise SystemExit("stock lib not found")
    build(PRESETS.get(args.preset, DEFAULT_COLORS), DEFAULT_ENABLED,
          stock, args.out)
