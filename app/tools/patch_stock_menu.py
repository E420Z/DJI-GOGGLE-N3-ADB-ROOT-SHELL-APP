"""Build a stock-UI menu action that launches the N3 overlay.

Static patch, no runtime hooks:
  * overwrite ``DuMenuItemsEntryActions_GalleryPageEntryAction`` (0x601f100)
  * stub calls dlsym(RTLD_DEFAULT, "system") via the GOT, then
    system("touch /data/local/tmp/n3_app_on")
  * the n3menu preload sees the flag and shows the overlay

The Gallery row is repurposed until we can add a real row. Recovery is the
normal Recover stock UI / revert path.

Usage:
    py -3.12 app/tools/patch_stock_menu.py --dry-run
    py -3.12 app/tools/patch_stock_menu.py --install
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl  # noqa: E402

STOCK = os.path.join(APP, "assets", "libew_gls_stock.so")
OUT = os.path.join(APP, "state", "libew_gls_menu.so")
MENU_LOCAL = os.path.join(APP, "plugins", "n3menu", "files", "n3menu.so")

# GalleryPageEntryAction: VA and file offset (text: addr 0x5dd9640, off 0x5dd8640)
TARGET_VA = 0x601F100
TARGET_OFF = 0x601E100
TARGET_SIZE = 248
# .got.plt dlsym slot (from .rela.plt)
DLSYM_GOT = 0x6324208
DLSYM_GOT_PAGE = DLSYM_GOT & ~0xFFF
DLSYM_GOT_OFF = DLSYM_GOT & 0xFFF


def adr(rd: int, pc: int, target: int) -> int:
    imm = target - pc
    return 0x10000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def adrp(rd: int, pc: int, target: int) -> int:
    base = pc & ~0xFFF
    imm = ((target & ~0xFFF) - base) >> 12
    return 0x90000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def ldr_x(rt: int, rn: int, off: int) -> int:
    return 0xF9400000 | ((off // 8) << 10) | (rn << 5) | rt


def blr(rn: int) -> int:
    return 0xD63F0000 | (rn << 5)


def cbz_x(rt: int, pc: int, target: int) -> int:
    off = (target - pc) >> 2
    return 0xB4000000 | ((off & 0x7FFFF) << 5) | rt


def build_stub() -> bytes:
    base = TARGET_VA
    sysname = base + 0x30
    cmd = base + 0x37
    done = base + 0x28
    ins = []
    ins.append(0xA9BF7BFD)                 # stp x29,x30,[sp,#-16]!
    ins.append(0x910003FD)                 # mov x29,sp
    ins.append(adrp(16, base + 8, DLSYM_GOT_PAGE))
    ins.append(ldr_x(17, 16, DLSYM_GOT_OFF))
    ins.append(adr(1, base + 16, sysname))
    ins.append(0xAA1F03E0)                 # mov x0,xzr
    ins.append(blr(17))
    ins.append(cbz_x(0, base + 28, done))
    ins.append(adr(1, base + 32, cmd))
    ins.append(blr(0))
    ins.append(0xA8C17BFD)                 # ldp x29,x30,[sp],#16
    ins.append(0xD65F03C0)                 # ret
    code = b"".join(struct.pack("<I", x) for x in ins)
    pad = sysname - (base + len(code))
    code += b"\0" * pad
    code += b"system\0"
    cmd_off = cmd - (base + len(code))
    code += b"\0" * cmd_off
    code += b"touch /data/local/tmp/n3_app_on\0"
    return code, ins


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(STOCK):
        print("missing stock lib:", STOCK)
        return 1
    data = bytearray(open(STOCK, "rb").read())
    orig = bytes(data[TARGET_OFF:TARGET_OFF + 16])
    print("target prologue:", orig.hex())
    if orig[:4] != b"\xfd\x7b\xbe\xa9":
        print("unexpected target prologue; refusing")
        return 1

    stub, ins = build_stub()
    print("stub size:", len(stub), "capacity:", TARGET_SIZE)
    if len(stub) > TARGET_SIZE:
        print("stub too large")
        return 1

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    print("stub disassembly:")
    for i in md.disasm(stub[:len(ins) * 4], TARGET_VA):
        print("  %#x %-8s %s" % (i.address, i.mnemonic, i.op_str))
    print("strings:", stub[0x30:0x30 + 7], stub[0x37:])

    data[TARGET_OFF:TARGET_OFF + len(stub)] = stub
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as fh:
        fh.write(data)
    print("wrote:", OUT, len(data))

    if args.install:
        n3ctl.ensure_adb(log=print)
        if not n3ctl.is_root():
            n3ctl.start_root(log=print)
        with n3ctl.vendor_write(log=print):
            n3ctl.push_file(MENU_LOCAL, "/vendor/n3menu.so", log=print)
            n3ctl.run_root("chmod 644 /vendor/n3menu.so", timeout=8, retries=1)
        print("installing patched lib + menu…")
        print("ok:", n3ctl.install_theme(OUT, log=print,
                                         mods=["/vendor/n3menu.so"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
