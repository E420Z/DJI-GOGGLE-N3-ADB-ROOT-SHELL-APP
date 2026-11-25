#!/usr/bin/env python3
"""N3 backup / recovery CLI for Linux (ADB only).

This is the safety net for Linux users: it backs up and restores the /vendor
mod/theme files over ADB, and can reboot the goggles to restore the stock UI.

The Windows-specific dji_blackbox root-shell exploit is not reimplemented here.
Use it when ADB is already enabled (or reboot: the stock UI returns).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

FILES = [
    "/vendor/n3mods.so",
    "/vendor/n3menu.so",
    "/vendor/n3live.so",
    "/vendor/hook_capture.so",
    "/vendor/n3paint.so",
    "/vendor/n3bg.so",
    "/vendor/n3_texttint.so",
    "/vendor/n3_bitmap.so",
    "/vendor/n3_ewtrace.so",
    "/vendor/background.jpg",
    "/vendor/background_idle.jpg",
    "/vendor/dji_glasses_patched",
    "/vendor/libew_gls.so",
    "/data/local/tmp/n3mods.list",
    "/data/local/tmp/usb_adb.sh",
    "/data/local/tmp/stock_usb.sh",
]
THEME_LIB = "/vendor/libew_gls.so"


def find_adb() -> str:
    env = os.environ.get("ADB")
    if env and os.path.exists(env):
        return env
    p = shutil.which("adb")
    if p:
        return p
    for cand in ("/usr/bin/adb", "/usr/local/bin/adb",
                 os.path.expanduser("~/platform-tools/adb")):
        if os.path.exists(cand):
            return cand
    raise SystemExit("adb not found; install platform-tools or set ADB=...")


def run(adb: str, args, timeout=120, check=False):
    p = subprocess.run([adb] + args, capture_output=True, text=True,
                       timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p


def info(adb: str):
    print("== adb devices ==")
    print(run(adb, ["devices", "-l"]).stdout.strip())
    for prop in ("ro.product.model", "ro.build.version.release",
                 "ro.build.display.id"):
        p = run(adb, ["shell", "getprop", prop])
        print("%-24s %s" % (prop, p.stdout.strip()))
    print("== /vendor (n3 files) ==")
    p = run(adb, ["shell", "ls -l /vendor 2>/dev/null | grep -E 'n3|hook|background|dji_glasses_patched' || true"])
    print(p.stdout.strip() or "(none / no permission)")
    print("== /data/local/tmp ==")
    p = run(adb, ["shell", "ls -l /data/local/tmp 2>/dev/null | grep -E 'n3|fb_|screencap' || true"])
    print(p.stdout.strip() or "(none / no permission)")


def backup(adb: str, out: str, with_theme_lib: bool):
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(out, "n3-backup-" + stamp)
    os.makedirs(dest, exist_ok=True)
    manifest = []
    for remote in FILES:
        if remote == THEME_LIB and not with_theme_lib:
            continue
        local = os.path.join(dest, remote.lstrip("/").replace("/", "__"))
        p = run(adb, ["pull", remote, local], timeout=300)
        ok = os.path.exists(local)
        size = os.path.getsize(local) if ok else 0
        print(("OK  " if ok else "skip") , remote, size)
        if ok:
            manifest.append({"remote": remote, "local": os.path.basename(local),
                             "size": size})
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"created": stamp, "device": run(adb, ["get-serialno"]).stdout.strip(),
                   "files": manifest}, f, indent=2)
    print("backup written to", dest)
    return dest


def restore(adb: str, src: str):
    man = os.path.join(src, "manifest.json")
    if not os.path.exists(man):
        raise SystemExit("no manifest.json in " + src)
    data = json.load(open(man, encoding="utf-8"))
    print("Remounting /vendor read-write (may fail without root)…")
    run(adb, ["shell", "mount -o remount,rw /vendor"])
    for item in data["files"]:
        local = os.path.join(src, item["local"])
        if not os.path.exists(local):
            print("missing", local)
            continue
        p = run(adb, ["push", local, item["remote"]], timeout=300)
        print(("OK  " if p.returncode == 0 else "FAIL"), item["remote"],
              (p.stderr or "").strip())
    run(adb, ["shell", "sync"])
    run(adb, ["shell", "mount -o remount,ro /vendor"])
    print("restore done. Reboot or restart the UI to apply.")


def reboot(adb: str):
    print("Rebooting goggles (stock UI returns on boot)…")
    run(adb, ["reboot"])
    try:
        run(adb, ["wait-for-device"], timeout=120)
        print("device is back")
    except Exception:
        print("device did not return to ADB; unplug/replug or power cycle")


def main():
    ap = argparse.ArgumentParser(description="N3 backup/recovery over ADB")
    ap.add_argument("--adb", help="path to adb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    b = sub.add_parser("backup")
    b.add_argument("--out", default=".", help="output directory")
    b.add_argument("--with-theme-lib", action="store_true",
                   help="also pull the 100 MB /vendor/libew_gls.so")
    r = sub.add_parser("restore")
    r.add_argument("--from", dest="src", required=True)
    sub.add_parser("reboot")
    args = ap.parse_args()

    adb = args.adb or find_adb()
    if args.cmd == "info":
        info(adb)
    elif args.cmd == "backup":
        backup(adb, args.out, args.with_theme_lib)
    elif args.cmd == "restore":
        restore(adb, args.src)
    elif args.cmd == "reboot":
        reboot(adb)


if __name__ == "__main__":
    main()
