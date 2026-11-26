"""Deploy the stock-menu row injector and show its log.

Usage (goggles connected with ADB):
    py -3.12 app/tools/deploy_menu_inject.py
    py -3.12 app/tools/deploy_menu_inject.py --enable
    py -3.12 app/tools/deploy_menu_inject.py --logs

Without --enable the mod only logs which stock menu reloads and its item count.
With --enable it also adds the 'N3' row on the next menu open.
"""
from __future__ import annotations

import argparse
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl  # noqa: E402

LOADER = os.path.join(APP, "assets", "mods", "n3mods.so")
MOD = os.path.join(APP, "plugins", "menuinject", "files", "n3menuinject.so")
VENDOR_MOD = "/vendor/n3menuinject.so"
PANEL = os.path.join(APP, "plugins", "n3menu", "files", "n3menu.so")
VENDOR_PANEL = "/vendor/n3menu.so"
FLAG = "/data/local/tmp/n3menuinject_on"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable", action="store_true",
                    help="create the injection flag (adds the N3 row)")
    ap.add_argument("--disable", action="store_true",
                    help="remove the injection flag (log-only)")
    ap.add_argument("--logs", action="store_true", help="only print logs")
    args = ap.parse_args()

    n3ctl.ensure_adb(log=print)
    if not n3ctl.is_root():
        n3ctl.start_root(log=print)

    if args.logs:
        print(n3ctl.run_root(
            "echo '== n3mods.log =='; tail -40 /data/local/tmp/n3mods.log "
            "2>/dev/null; echo '== natartos.log =='; tail -60 "
            "/data/local/tmp/natartos.log 2>/dev/null; echo '== ui log =='; "
            "tail -20 /data/local/tmp/dji_glasses.log 2>/dev/null",
            timeout=10, retries=1))
        return 0

    for p in (LOADER, MOD, PANEL):
        if not os.path.exists(p):
            print("missing:", p)
            return 1

    with n3ctl.vendor_write(log=print):
        n3ctl.push_file(LOADER, "/vendor/n3mods.so", log=print)
        n3ctl.push_file(MOD, VENDOR_MOD, log=print)
        n3ctl.push_file(PANEL, VENDOR_PANEL, log=print)
        n3ctl.run_root(
            "chmod 755 /vendor/n3mods.so %s %s; rm -f "
            "/data/local/tmp/n3mods.log /data/local/tmp/natartos.log "
            "/data/local/tmp/n3_app_on" % (VENDOR_MOD, VENDOR_PANEL),
            timeout=8, retries=1)

    if args.enable:
        n3ctl.run_root("touch %s" % FLAG, timeout=6, retries=1)
    elif args.disable:
        n3ctl.run_root("rm -f %s" % FLAG, timeout=6, retries=1)

    # The vendor remount drops ADB/root; bring it back before starting the UI.
    n3ctl.ensure_adb(log=print)
    print("loader exists:", n3ctl.dev_exists("/vendor/n3mods.so"))
    print("restarting UI with the injector...")
    ok = n3ctl.start_ui(log=print, mods=[VENDOR_MOD, VENDOR_PANEL])
    print("start_ui:", ok)
    print(n3ctl.run_root(
        "echo '== n3mods.log =='; cat /data/local/tmp/n3mods.log 2>/dev/null; "
        "echo '== natartos.log =='; cat /data/local/tmp/natartos.log 2>/dev/null",
        timeout=10, retries=1))
    print("\nNow open the stock menu. Then run:")
    print("  py -3.12 app/tools/deploy_menu_inject.py --logs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
