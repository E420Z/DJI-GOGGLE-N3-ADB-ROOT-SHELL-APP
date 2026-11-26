import struct
from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
f = open(P, "rb")
elf = ELFFile(f)

# sections
secs = []
for s in elf.iter_sections():
    secs.append((s.name, s["sh_addr"], s["sh_offset"], s["sh_size"]))
def va2sec(va):
    for name, ad, of, sz in secs:
        if ad and ad <= va < ad + sz:
            return name, of + (va - ad)
    return None, None

# dynamic symbols
dyn = elf.get_section_by_name(".dynsym")
dstr = elf.get_section_by_name(".dynstr")
strtab = dstr.data()
def dn(off):
    e = strtab.find(b"\0", off)
    return strtab[off:e].decode("ascii", "replace")

want = {"system", "popen", "open", "openat", "write", "close", "execl",
        "fork", "execve", "sh", "property_set", "dlopen", "dlsym"}
syms = {}
for sym in dyn.iter_symbols():
    nm = sym.name
    if nm in want:
        syms.setdefault(nm, []).append((sym["st_value"], sym["st_size"],
                                        sym["st_shndx"]))
print("libc imports of interest:")
for k, v in sorted(syms.items()):
    for va, sz, sh in v:
        print("  %-12s %#x size %d shndx %s" % (k, va, sz, sh))

# relocations
rel = elf.get_section_by_name(".rela.dyn")
targets = {
    0x601f100: "GalleryPageEntryAction",
    0x601f060: "DebugUnitMenuEntryAction",
    0x601f010: "AppSettingsEntryAction",
    0x6023020: "TriggerScriptNo1",
    0x601ef70: "StatusMenuEntryAction",
    0x6023170 if False else 0x6023160: "TriggerScriptNo5",
}
print("\nrelocations targeting menu actions:")
found = 0
if rel:
    off = rel["sh_offset"]
    size = rel["sh_size"]
    ent = rel["sh_entsize"] or 24
    for i in range(size // ent):
        r_off, r_info, r_add = struct.unpack_from("<QQq", raw, off + i * ent)
        if r_add in targets:
            sec, so = va2sec(r_off)
            found += 1
            print("  %-28s r_offset=%#x (%s+%#x) type=%d addend=%#x" %
                  (targets[r_add], r_off, sec, so - (va2sec(sec)[1] if False else 0),
                   r_info & 0xffffffff, r_add))
            if sec:
                _, so = va2sec(r_off)
                print("      slot bytes:", raw[so:so + 24].hex())
print("found:", found)
