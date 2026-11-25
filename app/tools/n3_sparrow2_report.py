"""Read-only Sparrow2 report for DJI Goggles N3.

Collects the radio firmware inventory, shipped console/test tools, live DUSS
hosts, SDRS channel names, and one read-only ``sdr_shell help`` query. Writes
only to the local app ``state/`` folder; nothing is changed on the goggles.

Usage:
    py -3.12 app/tools/n3_sparrow2_report.py

The console is a factory-PC tool (DUSS host ``test:7`` = ``0x1e07``); on a
normal device the query is expected to fail with ``-1002``/``-1007``. This is
recorded, not treated as an error.
"""
from __future__ import annotations

import datetime
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl  # noqa: E402

OUT = os.path.join(APP, "state", "sparrow2_report.md")

COMMANDS = {
    "identity": (
        "getprop ro.product.device; getprop ro.boot.mode; "
        "getprop sys.usb.config; cat /proc/cmdline"
    ),
    "firmware": (
        "ls -l /vendor/modem_firmware/sparrow2/ 2>/dev/null; echo; "
        "ls -d /vendor/modem_firmware/sparrow2/*/ 2>/dev/null"
    ),
    "tools": (
        "ls -l /system/bin/sdr_shell "
        "/system/bin/test_sparrow2_link.sh "
        "/system/bin/test_sparrow2_tsync.sh "
        "/system/bin/test_sparrow2_hw_ver.sh "
        "/system/bin/test_reset_s2_link.sh "
        "/system/bin/test_sdrlog_e3t_uart5_link.sh "
        "/system/bin/test_rf.sh 2>/dev/null"
    ),
    "duss_hosts": (
        "grep -a '@/duss/mb' /proc/net/unix 2>/dev/null "
        "| sed 's/.*@/@/' | sort -u"
    ),
    "host_1e07": "grep -c '@/duss/mb/0x1e07' /proc/net/unix 2>/dev/null",
    "channels": (
        "grep -a -o '\"status\": [01], \"channel\": \"[a-z_0-9]*\"' "
        "/system/etc/dji.json 2>/dev/null | sort -u | head -60"
    ),
    "sdr_shell_help": "timeout 12 /system/bin/sdr_shell help 2>&1",
}


def main() -> int:
    if not n3ctl.start_root(log=print):
        print("ERROR: root shell unavailable")
        return 1
    result = {}
    try:
        for name, cmd in COMMANDS.items():
            try:
                result[name] = n3ctl.run_root(cmd, timeout=40, retries=1)
            except Exception as exc:  # noqa: BLE001
                result[name] = "ERROR: %s" % exc
    finally:
        n3ctl.stop_root(log=print)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Sparrow2 report",
        "",
        "Generated: %s (read-only; no factory mode, no writes)." % stamp,
        "",
        "## Identity / boot",
        "```",
        result.get("identity", "").strip(),
        "```",
        "",
        "## Firmware inventory",
        "```",
        result.get("firmware", "").strip(),
        "```",
        "",
        "## Shipped console / test tools",
        "```",
        result.get("tools", "").strip(),
        "```",
        "",
        "## Live DUSS hosts",
        "```",
        result.get("duss_hosts", "").strip(),
        "```",
        "",
        "`test:7` host (`0x1e07`) present: **%s**" %
        ("yes" if result.get("host_1e07", "").strip() not in ("", "0") else "no"),
        "",
        "## SDRS channel status entries",
        "```",
        result.get("channels", "").strip(),
        "```",
        "",
        "## Console query (`sdr_shell help`)",
        "```",
        result.get("sdr_shell_help", "").strip(),
        "```",
        "",
        "## Interpretation",
        "",
        "- No AP-side IQ/ADC/FFT channel is exposed; the SDRS channels are",
        "  UART/DA logs and a disabled crash dump.",
        "- `sdr_shell` is a factory-PC tool. Without the `0x1e07` host it",
        "  returns `-1002`/`-1007`; that is expected on a normal device.",
        "- See `docs/SPARROW2.md` and `docs/SPARROW2-EVIDENCE.md`.",
        "",
    ]
    report = "\n".join(lines)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(report)
    print(report)
    print("saved:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
