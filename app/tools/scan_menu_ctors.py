"""Find direct branch callers of key N3 menu-construction functions."""
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
elf = ELFFile(open(P, "rb"))
text = elf.get_section_by_name(".text")
starts = {}
for s in elf.get_section_by_name(".dynsym").iter_symbols():
    if s["st_value"] and s.name:
        starts.setdefault(s["st_value"], s.name)

TARGETS = {
    0x60CA8C0: "DuThemedControlsMainMenu__Init",
    0x60D7A90: "DuThemedControlsMoreMenu__Init",
    0x5FFF970: "DuMenuItemsItemCollection__Init",
    0x5FFFA40: "DuMenuItemsEntryActions__Init",
    0x5FFE930: "DuMenuEntranceMenuEntranceLayer__Init",
    0x6134340: "MxMenuDefinitionMenu_AddItem2",
    0x60FB710: "MxBindableAbstractMenu_AddItemFromData",
}

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True
code = raw[text["sh_offset"]:text["sh_offset"] + text["sh_size"]]
found = {v: [] for v in TARGETS}
for i in md.disasm(code, text["sh_addr"]):
    if i.mnemonic in ("bl", "b") and i.operands and i.operands[0].type == 2:
        t = i.operands[0].imm
        if t in found:
            found[t].append(i.address)

for va, name in TARGETS.items():
    print("\n%s @ %#x  callers=%d" % (name, va, len(found[va])))
    for c in found[va][:20]:
        print("   %#x  %s" % (c, starts.get(c, "")))
