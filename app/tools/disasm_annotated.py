import bisect, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
elf = ELFFile(open(P, "rb"))
secs = [(s.name, s["sh_addr"], s["sh_offset"], s["sh_size"])
        for s in elf.iter_sections()]
def va2off(va):
    for name, ad, of, sz in secs:
        if ad and ad <= va < ad + sz:
            return of + (va - ad)
    return None

syms = []
for s in elf.get_section_by_name(".dynsym").iter_symbols():
    if s["st_value"] and s["st_size"]:
        syms.append((s["st_value"], s["st_size"], s.name))
syms.sort()
starts = [x[0] for x in syms]
def resolve(va):
    i = bisect.bisect_right(starts, va) - 1
    if i >= 0:
        st, sz, nm = syms[i]
        if va < st + sz:
            return "%s+%#x" % (nm, va - st)
        return "%s+%#x" % (nm, va - st)
    return "%#x" % va

def dis(name, va, size):
    off = va2off(va)
    print("\n==== %s @ %#x ====" % (name, va))
    if off is None:
        print("  no map")
        return
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    for i in md.disasm(raw[off:off + size], va):
        text = i.op_str
        if i.mnemonic in ("bl", "b") and i.operands and i.operands[0].type == 2:
            text = resolve(i.operands[0].imm)
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, text))

dis("Layer__Init", 0x5ffe930, 796)
dis("Left__Init", 0x5ffe720, 160)
dis("MxMenuDefinitionMenu__Init", 0x6133ac0, 68)
dis("EntryActions__Init", 0x5fffa40, 96)
dis("GalleryEntry", 0x601f100, 120)
dis("popUpMainMenu", 0x5ffec50, 52)
