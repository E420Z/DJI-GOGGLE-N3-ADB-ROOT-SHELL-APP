import struct, sys, re
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

P = r"C:\N3 goggles\N3-ROOT\app\assets\dji_glasses_vendor"
raw = open(P, "rb").read()
print("size", len(raw), "magic", raw[:4])
elf = ELFFile(open(P, "rb"))
print("type", elf.header["e_type"], "machine", elf.header["e_machine"],
      "entry", hex(elf.header["e_entry"]))
print("sections:")
for s in elf.iter_sections():
    if s.name in (".text", ".rodata", ".data", ".dynsym", ".dynstr", ".plt",
                  ".got", ".got.plt", ".rela.dyn", ".rela.plt"):
        print("  %-12s addr=%#x off=%#x size=%d" %
              (s.name, s["sh_addr"], s["sh_offset"], s["sh_size"]))

dyn = elf.get_section_by_name(".dynsym")
syms = []
if dyn:
    for s in dyn.iter_symbols():
        if s.name:
            syms.append((s["st_value"], s["st_size"], s.name))
    print("\ndynsym count", len(syms))
    for v, sz, nm in sorted(syms):
        if re.search(r"main|Ew|Mx|Core|dlopen|dlsym|display|input|Bsp|bsp|app|App|glasses|ui|UI", nm):
            print("  %#010x %6d %s" % (v, sz, nm))

print("\nstrings of interest:")
seen = set()
for m in re.finditer(rb"[ -~]{4,120}", raw):
    s = m.group().decode("ascii", "ignore")
    if not re.search(r"libew|Ew|Mx|dlopen|dlsym|display|input|Bsp|glasses|dji|\.so|main|argv|DUSS|duss", s):
        continue
    if s in seen:
        continue
    seen.add(s)
    if len(seen) <= 200:
        print("  ", s)
print("string hits", len(seen))
