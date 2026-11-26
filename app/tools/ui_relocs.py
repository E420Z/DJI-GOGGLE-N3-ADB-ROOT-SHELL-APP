import struct
from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
f = open(P, "rb")
elf = ELFFile(f)
data = f.read() if False else None
# read whole file
f.seek(0)
raw = f.read()

rel = elf.get_section_by_name(".rela.dyn")
relocs = {}
if rel:
    off = rel["sh_offset"]
    size = rel["sh_size"]
    ent = rel["sh_entsize"] or 24
    for i in range(size // ent):
        r_off, r_info, r_add = struct.unpack_from("<QQq", raw, off + i * ent)
        relocs[r_off] = r_add
print("rela.dyn entries:", len(relocs))

# section map
secs = []
for s in elf.iter_sections():
    secs.append((s.name, s["sh_addr"], s["sh_offset"], s["sh_size"]))
def va2off(va):
    for name, ad, of, sz in secs:
        if ad and ad <= va < ad + sz:
            return of + (va - ad)
    return None
def cstr(va, n=96):
    o = va2off(va)
    if o is None:
        return None
    b = raw[o:o + n]
    return b.split(b"\0")[0]

def dump(name, va, n=48):
    print("\n==== %s @ %#x ====" % (name, va))
    o = va2off(va)
    if o is None:
        print("  no map")
        return
    b = raw[o:o + n]
    print("  hex", b.hex())
    for j in range(0, n, 8):
        v = struct.unpack_from("<Q", b, j)[0]
        rv = relocs.get(va + j)
        print("  +%-2d raw=%#x reloc=%s" % (j, v, hex(rv) if rv is not None else "-"))
        tgt = rv if rv is not None else v
        if tgt and 0x10000 < tgt < len(raw):
            oo = va2off(tgt)
            if oo is not None:
                s = raw[oo:oo + 96].split(b"\0")[0]
                print("        -> %r" % s)
                # try utf-16
                u = raw[oo:oo + 96]
                try:
                    print("        u16-> %r" % u.decode("utf-16le", "ignore").split("\x00")[0][:60])
                except Exception:
                    pass

dump("eis_hb_list", 0x62a8d40)
dump("temp_warning", 0x6223de0)
dump("about_ok", 0x06240988)
dump("gallery_action", 0x601f100, 32)
dump("menu_entrance_vmt", 0x61fe250 if False else 0x5ffe250, 32)
