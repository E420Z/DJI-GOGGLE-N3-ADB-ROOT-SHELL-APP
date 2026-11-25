"""Read-only probe of the N3 for radio/ADC/video paths.

Collects device evidence only: ls/cat/getprop/dmesg/find/grep. No writes.
"""
from __future__ import annotations

import datetime
import os
import re
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl

STAMP = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUT = os.path.join(APP, "state", "evidence", STAMP)
os.makedirs(OUT, exist_ok=True)

CMDS = [
    ("identity", "uname -a; cat /proc/version; getprop ro.product.device; "
                 "getprop ro.product.model; getprop ro.build.display.id; "
                 "getprop ro.board.platform; getprop ro.hardware"),
    ("cpuinfo", "cat /proc/cpuinfo"),
    ("device_tree_model", "cat /proc/device-tree/model 2>/dev/null; echo; "
                          "cat /proc/device-tree/compatible 2>/dev/null | tr '\\0' '\\n'"),
    ("dev_list", "ls -l /dev"),
    ("dev_rf_video", "ls -l /dev/dji* /dev/video* /dev/iio* /dev/diag /dev/ion "
                     "/dev/dma* /dev/duss* /dev/disp* /dev/wwan* /dev/ttyS* 2>/dev/null"),
    ("class_list", "ls -l /sys/class"),
    ("class_rf_video", "ls -l /sys/class/video4linux /sys/class/iio /sys/class/drm "
                       "/sys/class/udc /sys/class/wwan /sys/class/net 2>/dev/null"),
    ("iio_devices", "find /sys/bus/iio /sys/class/iio -maxdepth 3 2>/dev/null"),
    ("display_nodes", "ls -l /proc/display 2>/dev/null; cat /proc/display/plane 2>/dev/null; "
                      "cat /proc/display/testcmd 2>/dev/null; ls -l /dev/dji_display 2>/dev/null"),
    ("system_bins", "ls /system/bin | grep -Ei 'dji|sdr|disp|test|modem|fastboot|brload|uvc|v4l|iq|adc'"),
    ("vendor_bins", "ls /vendor/bin /vendor/lib64 2>/dev/null | grep -Ei "
                    "'dji|sdr|disp|modem|uvc|v4l|iq|adc' | head -120"),
    ("modem_fw", "find /vendor/modem_firmware -maxdepth 3 -type f 2>/dev/null | head -120"),
    ("configs", "ls -l /vendor/etc /system/etc 2>/dev/null | grep -Ei "
                "'dji|sdr|wlm|gfsk|modem|display|media|uvc|video'"),
    ("dji_json_hits", "grep -a -i -E 'sdr|sparrow|pigeon|modem|iq|adc|fft|baseband|analog|demod|tuner|uvc|v4l' "
                      "/system/etc/dji.json /system/etc/device_table.json "
                      "/system/etc/wlm_cfg.json /system/etc/gfsk_agent_cfg.json 2>/dev/null | head -250"),
    ("dji_json", "cat /system/etc/dji.json 2>/dev/null"),
    ("kernel_modules", "cat /proc/modules 2>/dev/null"),
    ("interrupts", "cat /proc/interrupts 2>/dev/null"),
    ("iomem", "cat /proc/iomem 2>/dev/null"),
    ("kernel_config", "cat /proc/config.gz 2>/dev/null | gzip -d 2>/dev/null | "
                      "grep -Ei 'SDR|DVB|V4L|IIO|ADC|SPI|I2C|MODEM|USB_GADGET|UVC|MEDIA' | head -120"),
    ("props", "getprop | grep -Ei 'sdr|modem|rf|wlan|bt|lte|5g|uvc|video|display|analog|adc|dji' | head -250"),
    ("processes", "ps -A | grep -Ei 'dji|sdr|wlm|gfsk|media|uvc|disp|modem|adc|iq'"),
    ("dmesg_rf", "dmesg | grep -Ei 'sdr|sparrow|pigeon|modem|rf|adc|iq|fft|wlan|bt|nrf|5g|uvc|v4l|display|dsi|dss' | tail -250"),
    ("dmesg_tail", "dmesg | tail -350"),
    ("usb_devices", "for f in /sys/bus/usb/devices/*/idVendor; do "
                    "d=$(dirname $f); echo \"$d $(cat $f 2>/dev/null):$(cat $d/idProduct 2>/dev/null) "
                    "$(cat $d/product 2>/dev/null)\"; done"),
    ("udc", "ls -l /sys/class/udc 2>/dev/null; cat /sys/class/udc/*/state 2>/dev/null"),
    ("debugfs", "mount | grep -E 'debugfs|tracefs|configfs|functionfs'; "
                "ls -l /sys/kernel/debug 2>/dev/null | head -40; "
                "cat /sys/kernel/debug/usb/devices 2>/dev/null | head -160"),
    ("spi_i2c", "for d in /sys/bus/spi/devices/* /sys/bus/i2c/devices/*; do "
                "[ -e $d ] || continue; echo \"$d $(cat $d/modalias 2>/dev/null) "
                "$(cat $d/name 2>/dev/null)\"; done 2>/dev/null | head -160"),
    ("rf_nodes", "find /sys -maxdepth 5 \\( -iname '*sdr*' -o -iname '*adc*' -o "
                 "-iname '*iio*' -o -iname '*modem*' \\) 2>/dev/null | head -160"),
    ("blackbox", "ls -l /blackbox 2>/dev/null | head -60; "
                 "find /blackbox -maxdepth 3 \\( -iname '*sdr*' -o -iname '*uart*' \\) "
                 "2>/dev/null | head -60"),
    ("logcat_rf", "logcat -d -b all 2>/dev/null | grep -Ei "
                  "'sdr|sparrow|pigeon|iq|adc|fft|baseband|analog|demod|tuner' | tail -200"),
]


def main():
    if not n3ctl.start_root(log=print):
        print("no root shell")
        return 1
    summary = []
    for name, cmd in CMDS:
        print("=====", name)
        try:
            out = n3ctl.run_root(cmd, timeout=25, retries=1)
        except Exception as exc:  # noqa: BLE001
            out = "ERROR: %s" % exc
        path = os.path.join(OUT, name + ".txt")
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(out)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        print("  lines:", len(lines))
        for ln in lines[:6]:
            print("  ", ln[:180])
        summary.append((name, path, len(lines)))
    n3ctl.stop_root(log=print)

    with open(os.path.join(OUT, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# N3 radio/video read-only probe\n\n")
        f.write("Date: %s\n\n" % STAMP)
        f.write("| Probe | Lines | File |\n|---|---:|---|\n")
        for name, path, n in summary:
            f.write("| %s | %d | %s |\n" % (name, n, os.path.basename(path)))
    print("evidence:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
