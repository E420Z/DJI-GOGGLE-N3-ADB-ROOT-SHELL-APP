import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl

base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
print("evidence:", out)

cmds = {
 "wifi_dmesg": "dmesg | grep -i -E 'wlan|wifi|wcn|umw|rtl|bcm|qca|sdio|mmc|bluetooth|bt' | tail -250",
 "wifi_buses": "ls -l /sys/bus/sdio/devices /sys/bus/pci/devices /sys/class/net /sys/class/bluetooth /sys/class/ieee80211 2>/dev/null",
 "wifi_state": "cat /proc/net/wireless 2>/dev/null; rfkill list 2>/dev/null; cat /proc/modules 2>/dev/null | grep -Ei 'wlan|wifi|bt|bluetooth|cfg80211|mac80211'",
 "wifi_sysfs": "find /sys -maxdepth 6 \\( -iname '*wlan*' -o -iname '*wifi*' -o -iname '*sdio*' -o -iname '*bluetooth*' \\) 2>/dev/null | head -160",
 "wifi_cfg": "ls /vendor/etc/wifi /system/etc/wifi /vendor/firmware /vendor/lib64/modules 2>/dev/null | head -120",
 "wifi_props": "getprop | grep -i -E 'wifi|wlan|bt|bluetooth'",
 "wifi_bins": "ls /system/bin | grep -Ei 'wifi|wlan|bt|bluetooth|wpa'",
 "wifi_cli_strings": "grep -a -o -E '[ -~]{5,}' /system/bin/dji_wifi_cli 2>/dev/null | head -160",
 "net_dev": "cat /proc/net/dev",
 "mmc": "ls -l /sys/class/mmc_host 2>/dev/null; for d in /sys/class/mmc_host/*; do [ -e $d ] && echo $d $(cat $d/device/name 2>/dev/null); done",
 "pci": "ls -l /sys/bus/pci/devices 2>/dev/null; for d in /sys/bus/pci/devices/*; do [ -e $d ] && echo \"$d $(cat $d/vendor 2>/dev/null):$(cat $d/device 2>/dev/null) $(cat $d/class 2>/dev/null)\"; done | head -80",
 "sdio": "for d in /sys/bus/sdio/devices/*; do [ -e $d ] && echo \"$d $(cat $d/vendor 2>/dev/null):$(cat $d/device 2>/dev/null) $(cat $d/class 2>/dev/null)\"; done",
 "wifi_debugfs": "ls -l /sys/kernel/debug/ieee80211 2>/dev/null; find /sys/kernel/debug/ieee80211 -maxdepth 3 2>/dev/null | head -80",
}

if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=30, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:8]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")
