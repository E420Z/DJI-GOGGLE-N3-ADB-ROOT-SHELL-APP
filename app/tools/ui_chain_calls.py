import os, struct
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

def load(path):
    raw = open(path, "rb").read()
    elf = ELFFile(open(path, "rb"))
    plt = elf.get_section_by_name(".plt")
    rela = elf.get_section_by_name(".rela.plt")
    pltmap = {}
    if plt and rela:
        off, ent = rela["sh_offset"], rela["sh_entsize"] or 24
        for i in range(rela["sh_size"] // ent):
            r_off, r_info, _ = struct.unpack_from("<QQq", raw, off + i * ent)
            sym = elf.get_section_by_name(".dynsym").get_symbol(r_info >> 32)
            pltmap[plt["sh_addr"] + 16 * (i + 2)] = sym.name
    return raw, elf, pltmap

def dis(path, name, va, size, calls_only=False):
    raw, elf, pltmap = load(path)
    off = None
    for s in elf.iter_sections():
        if s["sh_addr"] and s["sh_addr"] <= va < s["sh_addr"] + s["sh_size"]:
            off = s["sh_offset"] + (va - s["sh_addr"])
            break
    print("\n==== %s %s @ %#x ====" % (os.path.basename(path), name, va))
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    prev = []
    for i in md.disasm(raw[off:off + size], va):
        tgt = None
        if i.operands and i.operands[0].type == 2:
            tgt = i.operands[0].imm
        if calls_only:
            if i.mnemonic in ("bl", "b"):
                t = pltmap.get(tgt, hex(tgt) if tgt else "")
                print("  %#010x  %-8s %s" % (i.address, i.mnemonic, t))
            elif i.mnemonic == "blr":
                print("  %#010x  blr      %s" % (i.address, i.op_str))
            continue
        if i.mnemonic in ("bl", "b") and tgt:
            t = pltmap.get(tgt, hex(tgt))
            print("  %#010x  %-8s %s" % (i.address, i.mnemonic, t))
        else:
            print("  %#010x  %-8s %s" % (i.address, i.mnemonic, i.op_str))

L = r"C:\N3 goggles\N3-ROOT\app\assets\dji_glasses_vendor"
S = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
for name, va, size in [("gs_gui_A", 0x1E8B0, 96), ("gs_gui_B", 0x1E8C0, 80),
                       ("gs_gui_C", 0x1E8D0, 80), ("gs_start", 0x3B0F0, 320),
                       ("gs_init", 0x3BD10, 320)]:
    dis(L, name, va, size)
dis(S, "ew_gui_start", 0x5DD9DE0, 992, calls_only=True)
dis(S, "ew_gui_stop", 0x5DDA530, 140, calls_only=True)
dis(S, "ew_gui_enable_key_event", 0x5DDA5C0, 64, calls_only=True)
dis(S, "ew_gui_disable_key_event", 0x5DDA600, 68, calls_only=True)
