import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

P = r"C:\N3 goggles\N3-ROOT\app\assets\libew_gls_stock.so"
raw = open(P, "rb").read()
TEXT_OFF, TEXT_VA = 0x5DD8640, 0x5DD9640

def dis(name, va, size):
    off = TEXT_OFF + (va - TEXT_VA)
    print("\n==== %s @ %#x size %d ====" % (name, va, size))
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for i in md.disasm(raw[off:off + size], va):
        print("  %#010x  %-8s %s" % (i.address, i.mnemonic, i.op_str))

dis("ItemCollection__Init", 0x5FFF970, 196)
dis("ItemCollection__ReInit", 0x5FFFB00, 52)
dis("ItemCollection__Done", 0x5FFFB70, 84)
dis("MenuItemDataByEnum head", 0x5FFFC00, 240)
dis("MenuItemDataByEnum mid", 0x6000000, 240)
