"""Annotated disassembly of the N3 stock menu controls.

Resolves direct branch targets to exact dynsym function starts so calls show
their real EW names instead of "+offset from a huge symbol".
"""
import os
import re

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
elf = ELFFile(open(P, "rb"))

secs = [(s.name, s["sh_addr"], s["sh_offset"], s["sh_size"])
        for s in elf.iter_sections()]
starts = {}
for s in elf.get_section_by_name(".dynsym").iter_symbols():
    if s["st_value"] and s.name:
        starts.setdefault(s["st_value"], s.name)


def va2off(va):
    for name, ad, of, sz in secs:
        if ad and ad <= va < ad + sz:
            return of + (va - ad)
    return None


def dis(name, va, size):
    off = va2off(va)
    print("\n==== %s @ %#x size %d ====" % (name, va, size))
    if off is None:
        print("  no map")
        return
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    for i in md.disasm(raw[off:off + size], va):
        text = i.op_str
        if (i.mnemonic in ("bl", "b")
                and i.operands
                and getattr(i.operands[0], "type", None) == 2):
            t = i.operands[0].imm
            text = starts.get(t, "%#x" % t)
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, text))


TARGETS = [
    ("DuMenuEntranceMenuEntranceLayer__Init", 0x5FFE930, 796),
    ("DuThemedControlsMainMenu__Init", 0x60CA8C0, 448),
    ("DuThemedControlsMainMenu_Init", 0x60CAA80, 120),
    ("DuThemedControlsMainMenuItemProvider_NewItem", 0x60CB190, 16),
    ("MxBindableAbstractMenu_Reload", 0x60FB600, 212),
    ("MxBindableAbstractMenu_AddItemFromData", 0x60FB710, 644),
    ("MxMenuDefinitionMenu_AddItem2", 0x6134340, 152),
    ("DuMenuItemsItemCollection__Init", 0x5FFF970, 196),
    ("DuMenuItemsEntryActions__Init", 0x5FFFA40, 96),
]

os.makedirs(r"C:\N3 goggles\N3-ROOT\app\state", exist_ok=True)
for name, va, size in TARGETS:
    dis(name, va, size)
