import re, struct
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

def syms(path, pat):
    elf = ELFFile(open(path, "rb"))
    out = []
    for s in elf.get_section_by_name(".dynsym").iter_symbols():
        if s.name and re.search(pat, s.name):
            out.append((s["st_value"], s["st_size"], s.name))
    out.sort()
    return out

for name, path in [
    ("loader", r"C:\N3 goggles\N3-ROOT\app\assets\dji_glasses_vendor"),
    ("stocklib", r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"),
]:
    print("=== %s ew_gui/gs entry symbols ===" % name)
    for v, sz, nm in syms(path, r"ew_gui|gs_gui|gs_entry|gs_mw|EwBsp|EwInit|EwMain"):
        print("  %#010x %6d %s" % (v, sz, nm))
