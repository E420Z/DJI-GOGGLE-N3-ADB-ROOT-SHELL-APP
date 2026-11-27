"""verify.py - PC-side check for the perma-ADB boot hook.

Read-only: it only runs `adb devices`, `adb shell getprop/id`, and
`adb shell ls`. It does not write anything.

Usage:
  py -3.12 verify.py
  py -3.12 verify.py --wait 120
"""
import argparse
import shutil
import subprocess
import sys
import time


def adb(args, timeout=15):
    exe = shutil.which("adb")
    if not exe:
        return 127, "adb not found on PATH"
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def one(cmd, timeout=15):
    rc, out = adb(["shell", cmd], timeout=timeout)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for an adb device")
    a = ap.parse_args()

    deadline = time.time() + a.wait
    while True:
        rc, out = adb(["devices"])
        lines = [l for l in out.splitlines()
                 if l.strip() and not l.startswith("List of devices")]
        ready = any(len(l.split()) >= 2 and l.split()[-1] == "device"
                    for l in lines)
        if ready:
            break
        if time.time() >= deadline:
            print("[!] no adb device.")
            print(out or "adb unavailable")
            print("    Check: USB composition, cable, adb keys, and that the hook fired.")
            return 1
        time.sleep(2)

    print("== adb devices ==")
    print(out)
    print("\n== state ==")
    print(one("getprop sys.usb.state; getprop init.svc.adbd; "
              "getprop service.adb.root; getprop ro.debuggable; "
              "ls -l /data/dji/perma_ok /data/dji/perma_off 2>&1"))
    print("\n== identity ==")
    print(one("id; getenforce"))
    print("\n== log tail ==")
    print(one("tail -20 /data/dji/perma.log 2>&1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
