"""rootctl - guarded device-wide root helper over perma-ADB.

Requires `adb` on PATH and the perma-ADB root shell:
    adb shell id  ->  uid=0(root) ... context=u:r:su:s0

Usage:
    py rootctl.py check
    py rootctl.py ls /data/dji
    py rootctl.py cat /data/dji/perma.log
    py rootctl.py push local.bin /data/dji/local.bin
    py rootctl.py pull /data/dji/perma.log perma.log
    py rootctl.py exec "id; getprop ro.build.type"

Safety:
  - /system and /dev/block writes are always refused.
  - /proc and /sys writes are refused.
  - /vendor writes require --allow-vendor (AVB coverage unproven).
  - It never mounts/remounts and never runs adb remount.
  - exec is a real root shell; /system writes still brick.
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys


def adb_exe():
    exe = shutil.which("adb")
    if not exe:
        raise SystemExit("adb not found on PATH")
    return exe


def run(args, binary=False, timeout=180):
    r = subprocess.run([adb_exe()] + args, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout)
    if binary:
        sys.stdout.buffer.write(r.stdout)
        sys.stdout.buffer.flush()
        if r.stderr:
            sys.stderr.buffer.write(r.stderr)
            sys.stderr.buffer.flush()
    else:
        sys.stdout.write(r.stdout.decode("utf-8", "replace"))
        if r.stderr:
            sys.stderr.write(r.stderr.decode("utf-8", "replace"))
    return r.returncode


def norm(path):
    return path.replace("\\", "/")


def guard_write(path, allow_vendor=False):
    p = norm(path)
    if not p.startswith("/"):
        raise SystemExit("remote path must be absolute: %s" % path)
    if p == "/" or p == "":
        raise SystemExit("refusing to write the root directory")
    if p == "/system" or p.startswith("/system/"):
        raise SystemExit("refusing /system write: dm-verity, brick on reboot")
    if p.startswith(("/dev/block", "/proc", "/sys")):
        raise SystemExit("refusing write to %s" % p)
    if (p == "/vendor" or p.startswith("/vendor/")) and not allow_vendor:
        raise SystemExit("refusing /vendor write without --allow-vendor "
                         "(AVB coverage unproven; runtime only)")
    return p


def check():
    print("== adb devices ==")
    run(["devices"])
    print("\n== identity ==")
    run(["shell", "id; getenforce"])
    print("\n== boot/USB state ==")
    run(["shell", "getprop ro.build.type; getprop ro.debuggable; "
                   "getprop sys.usb.state; getprop init.svc.adbd; "
                   "getprop service.adb.root"])
    print("\n== perma state ==")
    run(["shell", "ls -l /data/dji/perma_ok /data/dji/perma_off 2>&1; "
                   "tail -5 /data/dji/perma.log 2>&1"])
    print("\nNote: /system is never writable; /vendor needs --allow-vendor.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("ls")
    p.add_argument("path")
    p = sub.add_parser("cat")
    p.add_argument("path")
    p = sub.add_parser("push")
    p.add_argument("local")
    p.add_argument("remote")
    p = sub.add_parser("pull")
    p.add_argument("remote")
    p.add_argument("local")
    p = sub.add_parser("exec")
    p.add_argument("command")
    ap.add_argument("--allow-vendor", action="store_true",
                    help="allow /vendor writes (runtime only; AVB unproven)")
    a = ap.parse_args()

    if a.cmd == "check":
        return check()

    if a.cmd == "ls":
        return run(["shell", "ls -la " + shlex.quote(norm(a.path))])

    if a.cmd == "cat":
        return run(["exec-out", "cat " + shlex.quote(norm(a.path))], binary=True)

    if a.cmd == "push":
        if not os.path.exists(a.local):
            raise SystemExit("local file not found: %s" % a.local)
        remote = guard_write(a.remote, a.allow_vendor)
        if remote.startswith("/vendor"):
            print("[!] /vendor write: AVB coverage is unproven; this is a "
                  "runtime change and does not remount anything.", file=sys.stderr)
        return run(["push", a.local, remote])

    if a.cmd == "pull":
        return run(["pull", norm(a.remote), a.local])

    if a.cmd == "exec":
        print("[!] exec is a real root shell; /system writes still brick.",
              file=sys.stderr)
        return run(["shell", a.command])

    return 1


if __name__ == "__main__":
    sys.exit(main())
