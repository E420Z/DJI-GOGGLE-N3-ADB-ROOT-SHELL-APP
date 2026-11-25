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
 "dji_sys_fds": "p=$(ps -A | grep ' dji_sys$' | tr -s ' ' | cut -d' ' -f2 | head -1); echo PID=$p; ls -l /proc/$p/fd 2>/dev/null; echo '--- maps ---'; grep -Ei 'usbpri|usbfs|duss|dji|amt|sec|crypto|usb' /proc/$p/maps 2>/dev/null | head -80",
 "dji_sys_strings": "strings -n 4 /system/bin/dji_sys 2>/dev/null | grep -Ei 'MA Channel|AMT|antenna|measure|rf|test|factory|rpmb|key|calib|sdr|iq|adc|spectrum|raw|dump|usbpri|usbfs|bulk|interface' | head -220",
 "dji_sys_cfg": "grep -a -i -E 'dji_sys|MA Channel|AMT|antenna|measure|factory|test|rpmb|calib' /system/etc/dji.json /system/etc/commands.json 2>/dev/null | head -240",
 "dji_sys_log": "logcat -d -b all 2>/dev/null | grep -Ei 'dji_sys|AMT|MA Channel|antenna|measure|factory' | tail -160",
 "dji_sys_dmesg": "dmesg | grep -Ei 'MA Channel|AMT|dji_sys|antenna|measure' | tail -120",
 "iface3": "cat /sys/bus/usb/devices/2-1:1.3/interface 2>/dev/null; cat /sys/bus/usb/devices/2-1:1.3/bInterfaceNumber 2>/dev/null; cat /sys/bus/usb/devices/2-1:1.3/driver/uevent 2>/dev/null; ls -l /sys/bus/usb/devices/2-1:1.3/",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=35, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:14]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

