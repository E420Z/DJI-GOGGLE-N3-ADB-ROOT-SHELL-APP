import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl
base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
cmds = {
 "usbmon_avail": "ls -l /sys/kernel/debug/usb/usbmon 2>/dev/null; command -v timeout; command -v lsusb",
 "iface_strings": "for i in /sys/bus/usb/devices/2-1:1.*; do echo -n \"$i num=\"; cat $i/bInterfaceNumber 2>/dev/null; echo -n \" iface=\"; cat $i/interface 2>/dev/null; echo; done",
 "lsusb": "lsusb 2>/dev/null | head -40; lsusb -v -d 2ca3:1020 2>/dev/null | head -200",
 "usbmon_capture": "rm -f /data/local/tmp/usbmon_c5.txt; (timeout 2 cat /sys/kernel/debug/usb/usbmon/2u > /data/local/tmp/usbmon_c5.txt 2>/dev/null || head -4000 /sys/kernel/debug/usb/usbmon/2u > /data/local/tmp/usbmon_c5.txt 2>/dev/null); wc -l /data/local/tmp/usbmon_c5.txt; head -40 /data/local/tmp/usbmon_c5.txt; echo '--- endpoints/lengths ---'; awk '{print $3, $4, $5, $6, $7}' /data/local/tmp/usbmon_c5.txt | head -60",
 "usbmon_cleanup": "rm -f /data/local/tmp/usbmon_c5.txt; echo cleaned",
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
    for line in [x for x in txt.splitlines() if x.strip()][:12]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

