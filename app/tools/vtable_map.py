"""Dump EW vtables for the N3 menu controls with relocated slot targets.

Vtable entries are RELATIVE relocations in .data.rel.ro; resolving them shows
which slot holds Reload/Postreload/AddItem/etc. on this build.
"""
import struct

from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
elf = ELFFile(open(P, "rb"))

dynsym = elf.get_section_by_name(".dynsym")
dynstr = elf.get_section_by_name(".dynstr")
sym_by_addr = {}
for s in dynsym.iter_symbols():
    if s["st_value"] and s.name:
        sym_by_addr.setdefault(s["st_value"], s.name)

WANT = [
    "__vmt_DuThemedControlsMainMenu",
    "__vmt_DuThemedControlsMoreMenu",
    "__vmt_MxBindableAbstractMenu",
    "__vmt_DuMenuItemsItemCollection",
    "__vmt_DuThemedControlsMainMenuItemProvider",
]

info = {}
for name in WANT:
    s = dynsym.get_symbol_by_name(name)
    if not s:
        print("missing symbol", name)
        continue
    s = s[0]
    info[name] = (s["st_value"], s["st_size"])
    print("%-46s %#010x size %d" % (name, s["st_value"], s["st_size"]))

# relative relocations
relocs = {}
for secname in (".rela.dyn", ".rela.plt"):
    sec = elf.get_section_by_name(secname)
    if not sec:
        continue
    ent = sec["sh_entsize"] or 24
    for i in range(sec["sh_size"] // ent):
        off, rinfo, addend = struct.unpack_from("<QQq", raw, sec["sh_offset"] + i * ent)
        rtype = rinfo & 0xFFFFFFFF
        rsym = rinfo >> 32
        sname = ""
        if 0 < rsym < dynsym.num_symbols():
            sname = dynsym.get_symbol(rsym).name
        # R_AARCH64_RELATIVE = 1027
        relocs[off] = (rtype, sname, addend)

for name in WANT:
    if name not in info:
        continue
    base, size = info[name]
    print("\n=== %s @ %#x (%d slots) ===" % (name, base, size // 8))
    for idx in range(size // 8):
        va = base + idx * 8
        off = None
        for sec in elf.iter_sections():
            if sec["sh_addr"] and sec["sh_addr"] <= va < sec["sh_addr"] + sec["sh_size"]:
                off = sec["sh_offset"] + (va - sec["sh_addr"])
                break
        if off is None:
            continue
        # find relocation covering this 8-byte slot
        rel = relocs.get(va)
        if rel:
            rtype, sname, addend = rel
            target = sname or sym_by_addr.get(addend, "%#x" % addend)
            print("  [%2d] %#010x -> %s (type %d)" % (idx, va, target, rtype))
        else:
            rawv = struct.unpack_from("<Q", raw, off)[0]
            if rawv:
                tgt = sym_by_addr.get(rawv, "%#x" % rawv)
                print("  [%2d] %#010x = %s" % (idx, va, tgt))
