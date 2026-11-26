import struct, sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
data = open(P, "rb").read()
e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
secs = []
for i in range(e_shnum):
    o = e_shoff + i * e_shentsize
    nm, typ, fl, ad, of, sz, lk, inf, al, es = struct.unpack_from(
        "<IIQQQQIIQQ", data, o)
    secs.append(dict(nm=nm, typ=typ, addr=ad, off=of, size=sz))
shstr = data[secs[e_shstrndx]["off"]:secs[e_shstrndx]["off"] + secs[e_shstrndx]["size"]]
def sn(n):
    e = shstr.find(b"\0", n)
    return shstr[n:e].decode("ascii", "replace")
for s in secs:
    s["name"] = sn(s["nm"])

def va2off(va):
    for s in secs:
        if s["addr"] and s["addr"] <= va < s["addr"] + s["size"]:
            return s["off"] + (va - s["addr"])
    return None

def dis(name, va, size):
    off = va2off(va)
    print("\n==== %s @ %#x size %d off %s ====" %
          (name, va, size, hex(off) if off is not None else None))
    if off is None:
        print("  (no mapping)")
        return
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = False
    n = 0
    for i in md.disasm(data[off:off + size], va):
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, i.op_str))
        n += 1
        if n > 120:
            print("  ...")
            break

def obj(name, va, n=32):
    off = va2off(va)
    print("\n==== %s @ %#x off %s ====" %
          (name, va, hex(off) if off is not None else None))
    if off is None:
        return
    b = data[off:off + n]
    print("  hex:", b.hex())
    for i in range(0, n, 8):
        v = struct.unpack_from("<Q", b, i)[0]
        print("  +%-2d %#018x" % (i, v))
        if 0x1000 < v < len(data):
            o = va2off(v)
            if o:
                raw = data[o:o + 120]
                print("       ->", raw.split(b"\0")[0][:120])

dis("DuMenuEntranceMenuEntrance__Init", 0x05ffe250, 256)
dis("DuMenuEntranceMenuEntranceLayer_OnSetOnTapMenuEntranceTop", 0x05fff030, 84)
dis("DuMenuItemsEntryActions_GalleryPageEntryAction", 0x0601f100, 248)
dis("DuMenuItemsSettingActions__ReInit", 0x05fffb50, 8)
dis("MxMenuDefinitionMenu__Init", 0x06133ac0, 68)
dis("MxMenuDefinitionItemCollection_actionIndexedImage", 0x06136790, 320)

obj("str_eis_hb_list", 0x062a8d40, 24)
obj("str_temp_warning", 0x06223de0, 24)
obj("str_about_ok", 0x06240988, 24)
