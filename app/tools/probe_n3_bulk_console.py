"""On-goggles Sparrow2 console probe via a custom DUSS bulk route.

Idea: ``system_service/system/e0`` is a *bulk* route to ``vt_gnd`` over
``/bulk/s2`` (Sparrow2 USB interface 4), but it is disabled (``status: 0``).
The shipped ``test/diag/e0`` route is local to ``glass:1`` and only works in
factory mode. This tool builds a **custom route table** (``dji_mb_ctrl -J``)
that:

* enables a bulk ``e0`` route to ``vt_gnd`` over ``/bulk/s2``;
* uses a free source host ``test:9`` (``0x1e09``) instead of the owned
  ``system:1`` / ``test:7`` hosts.

Then it sends the same read-only console payload as ``sdr_shell``:
``cmd_set 9 / cmd 0x55 / 00 64 00 18 <ascii>\\r``.

This is experimental and untested on hardware. It only sends a read-only
``help`` query. It does not enter factory mode, flash, calibrate, or write to
the modem.

Usage:
    # build the custom JSON only (no device)
    py -3.12 app/tools/probe_n3_bulk_console.py --dry-run

    # run the probe (device connected, root shell available)
    py -3.12 app/tools/probe_n3_bulk_console.py --live --command help

    # try a different free source host index if 0x1e09 is rejected
    py -3.12 app/tools/probe_n3_bulk_console.py --live --host-index 0
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl  # noqa: E402

REMOTE_JSON = "/data/local/tmp/n3_sparrow_probe.json"
LOCAL_JSON = os.path.join(APP, "state", "n3_sparrow_probe.json")
REPORT = os.path.join(APP, "state", "sparrow2_bulk_probe.txt")


def find_base_json(explicit: str | None) -> str:
    if explicit:
        return explicit
    base = os.path.join(APP, "state", "evidence")
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True):
            path = os.path.join(base, name, "dji_json.txt")
            if os.path.exists(path):
                return path
    raise SystemExit(
        "no captured dji.json found; pass --dji-json PATH or --live")


def bulk_route(base: dict) -> dict:
    """Copy the disabled system->vt_gnd bulk route and enable it."""
    route = copy.deepcopy(
        base["system_service"]["mb_route_table"]["system"]["e0"])
    route["status"] = 1
    route["channel"] = "bulk"
    route["protocol"] = "v1"
    route["target"] = "vt_gnd"
    route["index"] = 0
    route["route_control"] = {
        "auto_switch": 1,
        "uevent_path": "/sys/bus/usb/devices/2-1",
    }
    route["bulk"] = {
        "dev": "/bulk/s2",
        "host": 1,
        "reconnect": 1,
        "ep_in": 133,      # 0x85
        "ep_out": 5,       # 0x05
        "vid": 11427,      # 0x2CA3 (Sparrow2)
        "pid": 4128,       # 0x1020
        "interface": 4,
        "open_by_device": 1,
    }
    return route


def build_probe(base: dict, host_index: int) -> dict:
    out = copy.deepcopy(base)
    out["sparrow_probe"] = {
        "mb_route_table": {
            "link": {
                "host": "test",
                "index": host_index,
                "e0": bulk_route(base),
            }
        }
    }
    return out


def payload(command: str) -> str:
    return "00640018" + (command + "\r").encode("ascii").hex()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dji-json", help="captured /system/etc/dji.json")
    ap.add_argument("--live", action="store_true",
                    help="read /system/etc/dji.json from the device")
    ap.add_argument("--host-index", type=int, default=9,
                    help="free source host index (test:<n>, default 9)")
    ap.add_argument("--command", default="help",
                    help="console command (default: help)")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the JSON only, do not touch the device")
    args = ap.parse_args()

    if args.live:
        if not n3ctl.start_root(log=print):
            print("ERROR: root shell unavailable")
            return 1
        try:
            raw = n3ctl.run_root("cat /system/etc/dji.json",
                                 timeout=40, retries=1)
        finally:
            n3ctl.stop_root(log=print)
        base = json.loads(raw)
    else:
        path = find_base_json(args.dji_json)
        print("base:", path)
        base = json.loads(open(path, encoding="utf-8",
                              errors="replace").read())

    probe = build_probe(base, args.host_index)
    text = json.dumps(probe, separators=(",", ":"))
    os.makedirs(os.path.dirname(LOCAL_JSON), exist_ok=True)
    with open(LOCAL_JSON, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote:", LOCAL_JSON, len(text), "bytes")
    print("source host: test:%d (0x1e%02x)" %
          (args.host_index, args.host_index))
    print("route: e0 -> vt_gnd 0 -> /bulk/s2 iface 4 ep 05/85 (status 1)")

    if args.dry_run:
        print("dry-run: no device access")
        return 0

    if not n3ctl.start_root(log=print):
        print("ERROR: root shell unavailable")
        return 1
    lines = ["# Sparrow2 bulk console probe",
             "time: %s" % datetime.datetime.now().isoformat(timespec="seconds"),
             "host-index: %d" % args.host_index,
             "command: %r" % args.command]
    try:
        print("pushing: %s -> %s" % (LOCAL_JSON, REMOTE_JSON))
        if not n3ctl.push_file(LOCAL_JSON, REMOTE_JSON, log=print):
            print("ERROR: push failed")
            return 1
        cmd = ("dji_mb_ctrl -J %s -S sparrow_probe -R link -m 2304 "
               "-o 4000000 -g 14 -t 0 -s 9 -c 0x55 %s 2>&1" %
               (REMOTE_JSON, payload(args.command)))
        print("run:", cmd)
        txt = n3ctl.run_root(cmd, timeout=45, retries=1)
        print(txt)
        lines += ["", "## run", "```", cmd, "```", "", "## output", "```",
                  txt.strip(), "```"]
    finally:
        try:
            n3ctl.run_root("rm -f %s" % REMOTE_JSON, timeout=10, retries=1)
        except Exception:
            pass
        n3ctl.stop_root(log=print)

    with open(REPORT, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved:", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
