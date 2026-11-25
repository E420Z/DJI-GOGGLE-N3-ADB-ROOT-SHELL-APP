"""Offline analysis of a captured ``dji.json`` (Sparrow2 channels/routes).

Reads the newest ``app/state/evidence/*/dji_json.txt`` and prints the SDRS log
channels, the ``/bulk`` device names, the DUSS route hosts for the test/AMT/
SDRS services, and any IQ/ADC/sample keys. No device access, no writes.

Usage:
    py -3.12 app/tools/analyze_sdrs_cfg.py
"""
from __future__ import annotations

import json
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(APP, "state", "evidence")


def newest_dji_json() -> str:
    if not os.path.isdir(BASE):
        raise SystemExit("no evidence dir; run probe_n3_radio.py first")
    dirs = sorted(d for d in os.listdir(BASE)
                  if os.path.isdir(os.path.join(BASE, d)))
    for name in reversed(dirs):
        path = os.path.join(BASE, name, "dji_json.txt")
        if os.path.exists(path):
            return path
    raise SystemExit("no dji_json.txt in evidence")


def main() -> int:
    path = newest_dji_json()
    print("source:", path)
    data = json.loads(open(path, encoding="utf-8", errors="replace").read())

    cfg = data.get("sdrs_agent_service", {}).get("configuration", {})
    channels = cfg.get("sdrs_log", {}).get("channel", {})
    print("\n=== SDRS log channels ===")
    for name, rec in channels.items():
        extra = rec.get("bulk_single") or rec.get("uart") or {}
        print("%-18s status=%s channel=%-12s %s" % (
            name, rec.get("status"), rec.get("channel"),
            json.dumps(extra) if extra else ""))

    print("\n=== /bulk devices in HAL ===")
    found = set()
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith("/bulk/"):
            found.add(o)
    walk(data.get("hal", {}))
    for name in sorted(found):
        print(name)

    print("\n=== DUSS route hosts ===")
    for svc in ("test", "amt_service", "sdrs_agent_service"):
        table = data.get(svc, {}).get("mb_route_table", {})
        for host, rec in table.items():
            print("%-20s host=%-12s index=%s routes=%d" % (
                svc, host, rec.get("index"),
                len([k for k in rec if k not in ("host", "index")])))

    print("\n=== IQ/ADC/sample/spectrum keys ===")
    hits = []
    def scan(o, pathp=""):
        if isinstance(o, dict):
            for k, v in o.items():
                p = pathp + "/" + str(k)
                if any(x in str(k).lower() for x in
                       ("iq", "adc", "sample", "spectrum", "fft")):
                    hits.append(p)
                scan(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                scan(v, pathp + "[%d]" % i)
    scan(data)
    print("\n".join(hits) if hits else "(none)")
    print("\nresult: no IQ/ADC/sample/spectrum keys found" if not hits
          else "\nresult: %d candidate key(s)" % len(hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
