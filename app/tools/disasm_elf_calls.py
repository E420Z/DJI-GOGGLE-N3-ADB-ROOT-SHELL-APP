import bisect, struct
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

def load(path):
    raw = open(path, "rb").read()
    elf = ELFFile(open(path, "rb"))
    secs = {s.name: s for s in elf.iter_sections()}
    syms = []
    for s in elf.get_section_by_name(".dynsym").iter_symbols():
        if s["st_value"]:
            syms.append((s["st_value"], s["st_size"], s.name))
    syms.sort()
    plt = secs.get(".plt")
    rela = secs.get(".rela.plt")
    pltmap = {}
    if plt and rela:
        off, ent = rela["sh_offset"], rela["sh_entsize"] or 24
        for i in range(rela["sh_size"] // ent):
            r_off, r_info, _ = struct.unpack_from("<QQq", raw, off + i * ent)
            sym = elf.get_section_by_name(".dynsym").get_symbol(r_info >> 32)
            pltmap[plt["sh_addr"] + 16 * (i + 2)] = sym.name
    return raw, elf, secs, syms, pltmap

def dis(path, name, va, size):
    raw, elf, secs, syms, pltmap = load(path)
    starts = [x[0] for x in syms]
    def resolve(t):
        if t in pltmap:
            return "PLT:" + pltmap[t]
        i = bisect.bisect_right(starts, t) - 1
        if i >= 0:
            st, sz, nm = syms[i]
            if st <= t < st + sz:
                return "%s+%#x" % (nm, t - st)
        return "%#x" % t
    # map VA to file offset
    off = None
    for s in elf.iter_sections():
        if s["sh_addr"] and s["sh_addr"] <= va < s["sh_addr"] + s["sh_size"]:
            off = s["sh_offset"] + (va - s["sh_addr"])
            break
    print("\n==== %s %s @ %#x ====" % (os.path.basename(path), name, va))
    if off is None:
        print(" no map")
        return
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    for i in md.disasm(raw[off:off + size], va):
        if i.mnemonic in ("bl", "b") and i.operands and i.operands[0].type == 2:
            print("  %#010x  %-8s %s" % (i.address, i.mnemonic,
                                          resolve(i.operands[0].imm)))
        else:
            print("  %#010x  %-8s %s" % (i.address, i.mnemonic, i.op_str))

import os
L = r"C:\N3 goggles\N3-ROOT\app\assets\dji_glasses_vendor"
S = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
dis(L, "main", 0x1D9E0, 2412)
dis(S, "ew_gui_start", 0x5DD9DE0, 992)
dis(S, "ew_gui_stop", 0x5DDA530, 140)
dis(S, "ew_gui_enable_key_event", 0x5DDA5C0, 64)
dis(S, "ew_gui_disable_key_event", 0x5DDA600, 68)
dis(S, "get_ew_gui_config", 0x5DDA650, 12)
