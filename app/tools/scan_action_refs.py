import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
TEXT_OFF, TEXT_VA, TEXT_SIZE = 0x5DD8640, 0x5DD9640, 3736984
text = raw[TEXT_OFF:TEXT_OFF + TEXT_SIZE]

targets = {
    0x601F100: "GalleryEntry",
    0x601F010: "AppSettingsEntry",
    0x601EF70: "StatusMenuEntry",
    0x601F060: "DebugUnitEntry",
    0x6023020: "TriggerScriptNo1",
    0x6023160: "TriggerScriptNo5",
}
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True
hits = 0
n = 0
for i in md.disasm(text, TEXT_VA):
    n += 1
    if i.mnemonic in ("bl", "b") and i.operands and i.operands[0].type == 2:
        t = i.operands[0].imm
        if t in targets:
            hits += 1
            print("branch %s -> %s at %#x" % (i.mnemonic, targets[t], i.address))
print("instructions", n, "hits", hits)

# raw 8-byte occurrences of the action VAs anywhere in the file
for va, name in targets.items():
    pat = struct.pack("<Q", va)
    offs = []
    start = 0
    while True:
        o = raw.find(pat, start)
        if o < 0:
            break
        offs.append(o)
        start = o + 1
    print("%s raw64 occurrences: %s" % (name, [hex(x) for x in offs[:10]]))
