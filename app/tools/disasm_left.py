import struct
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
    nm, typ, fl, ad, of, sz, lk, inf, al, es = struct.unpack_from("<IIQQQQIIQQ", data, o)
    secs.append((nm, ad, of, sz))
shstr = data[secs[e_shstrndx][2]:secs[e_shstrndx][2] + secs[e_shstrndx][3]]
def sn(n):
    e = shstr.find(b"\0", n)
    return shstr[n:e].decode("ascii", "replace")
secs = [(sn(nm), ad, of, sz) for nm, ad, of, sz in secs]
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
    for i in md.disasm(data[off:off + size], va):
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, i.op_str))

dis("Left__Init", 0x05ffe720, 160)
dis("Left__ReInit", 0x05ffe7c0, 44)
dis("Top__Init", 0x05ffe830, 140)
dis("Bottom__Init", 0x05ffe620, 140)
dis("Layer__Init", 0x05ffe930, 796)
dis("Layer__ReInit", 0x05ffee50, 108)
dis("Layer_popUpMainMenu", 0x05ffec50, 52)
