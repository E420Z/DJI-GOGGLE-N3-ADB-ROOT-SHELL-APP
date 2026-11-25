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
 "init_rcs": "ls -l /system/etc/init | grep -Ei 'dji|amt|sys|sdr|wlm'; echo '--- amt.rc ---'; cat /system/etc/init/dji_amt.rc 2>/dev/null; echo '--- system.rc ---'; cat /system/etc/init/dji_system.rc 2>/dev/null",
 "amt_fds": "p=$(ps -A | grep ' dji_amt$' | tr -s ' ' | cut -d' ' -f2 | head -1); echo PID=$p; [ -n \"$p\" ] && ls -l /proc/$p/fd 2>/dev/null; [ -n \"$p\" ] && echo '--- maps ---' && grep -Ei 'usb|duss|dji|amt|sec|crypto' /proc/$p/maps 2>/dev/null | head -60",
 "amt_strings": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'factory|amt|ma channel|measure|antenna|rf|test|calib|rpmb|key|usb|duss|cmd|mode' | head -200",
 "factory_cfg": "grep -R -a -i -E 'start_factory|stop_factory|factory|AMT|MA Channel|measure|antenna|calib' /system/etc/init /system/etc/dji.json 2>/dev/null | head -240",
 "sys_factory_json": "grep -a -n -i -E 'start_factory|stop_factory|factory|perf_test|dji_amt|amt_service' /system/etc/dji.json 2>/dev/null | head -120",
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

