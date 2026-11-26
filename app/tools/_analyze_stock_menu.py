import re, struct, os
P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
data = open(P, "rb").read()
print("size", len(data), "elf", data[:4])
e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
secs = []
for i in range(e_shnum):
    off = e_shoff + i * e_shentsize
    name, typ, flags, addr, offset, size, link, info, align, entsize = \
        struct.unpack_from("<IIQQQQIIQQ", data, off)
    secs.append(dict(name=name, typ=typ, addr=addr, offset=offset,
                     size=size, link=link, entsize=entsize))
shstr = data[secs[e_shstrndx]["offset"]:
             secs[e_shstrndx]["offset"] + secs[e_shstrndx]["size"]]
def sname(n):
    e = shstr.find(b"\0", n)
    return shstr[n:e].decode("ascii", "replace")
for s in secs:
    s["sname"] = sname(s["name"])
print("sections:")
for s in secs:
    if s["sname"] in (".dynsym", ".dynstr", ".symtab", ".strtab", ".text", ".rodata"):
        print(" ", s["sname"], hex(s["addr"]), hex(s["offset"]), s["size"], "entsize", s["entsize"])

# dynsym
by_name = {s["sname"]: s for s in secs}
if ".dynsym" in by_name and ".dynstr" in by_name:
    ds, st = by_name[".dynsym"], by_name[".dynstr"]
    strtab = data[st["offset"]:st["offset"] + st["size"]]
    def dname(n):
        e = strtab.find(b"\0", n)
        return strtab[n:e].decode("ascii", "replace")
    pat = re.compile(r"menu|item|select|click|tap|command|action|setting|view|launch|dialog|button", re.I)
    hits = []
    for i in range(ds["size"] // 24):
        off = ds["offset"] + i * 24
        st_name = struct.unpack_from("<I", data, off)[0]
        st_value = struct.unpack_from("<Q", data, off + 8)[0]
        nm = dname(st_name)
        if nm and pat.search(nm):
            hits.append((st_value, nm))
    print("dynamic symbol hits:", len(hits))
    for va, nm in hits[:120]:
        print("  %#x %s" % (va, nm))

# strings in the whole file (ASCII runs)
print("scanning strings...")
pat2 = re.compile(r"^(?:.*(?:menu|settings|about|gallery|wi-?fi|display|device|storage|n3|root|tool|info|exit|close).*)$", re.I)
seen = set()
count = 0
for m in re.finditer(rb"[ -~]{4,100}", data):
    s = m.group().decode("ascii", "ignore")
    if not pat2.match(s):
        continue
    if s in seen:
        continue
    seen.add(s)
    count += 1
    if count <= 160:
        print("  ", s)
print("string hits:", count)
