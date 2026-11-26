"""Disassemble stock menu entry actions with exact symbol resolution."""
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
    ("StatusMenuEntryAction", 0x601EF70, 152),
    ("AppSettingsEntryAction", 0x601F010, 68),
    ("DebugUnitMenuEntryAction", 0x601F060, 152),
    ("GalleryPageEntryAction", 0x601F100, 248),
    ("PcOtgEntryAction", 0x6021880, 100),
    ("WifiSinkEntryAction", 0x60231B0, 172),
    ("SimulatorEntryAction", 0x6023260, 116),
    ("DLNAEntryAction", 0x60232E0, 40),
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
