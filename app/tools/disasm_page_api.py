"""Disassemble the stock menu creation / popup / data-source APIs."""
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


def off(va):
    for _n, a, o, z in secs:
        if a and a <= va < a + z:
            return o + (va - a)
    return None


md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True

TARGETS = [
    ("MxBindableAbstractMenuDataSource__Init", 0x60FC190, 88),
    ("MxBindableAbstractMenuDataSource_Init", 0x60FC1F0, 48),
    ("MxBindableAbstractMenuDataSource_Size", 0x60FC240, 8),
    ("MxBindableAbstractMenuDataSource_At", 0x60FC250, 8),
    ("MxBindableAbstractMenu_OnSetDataSource", 0x60FB430, 372),
    ("MxBindableAbstractMenu_PopUp", 0x60FBAD0, 416),
    ("MxBindableAbstractMenu_PopUpWithBounds", 0x60FBF80, 420),
    ("MxBindableAbstractMenu_Dismiss", 0x60FBD00, 348),
    ("DuThemedControlsMainMenu_Init", 0x60CAA80, 120),
]

for name, va, size in TARGETS:
    print("\n==== %s @ %#x ====" % (name, va))
    o = off(va)
    if o is None:
        print("  no map")
        continue
    for i in md.disasm(raw[o:o + size], va):
        text = i.op_str
        if (i.mnemonic in ("bl", "b")
                and i.operands
                and getattr(i.operands[0], "type", None) == 2):
            t = i.operands[0].imm
            text = starts.get(t, "%#x" % t)
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, text))
