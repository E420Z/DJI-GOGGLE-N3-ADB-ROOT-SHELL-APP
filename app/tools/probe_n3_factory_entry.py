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
 "amt_rc": "echo '=== dji_amt.rc ==='; cat /system/etc/init/dji_amt.rc 2>/dev/null; echo '=== dji_system.rc ==='; cat /system/etc/init/dji_system.rc 2>/dev/null; echo '=== dji_blackbox.rc ==='; cat /system/etc/init/dji_blackbox.rc 2>/dev/null",
 "service_list": "service list 2>/dev/null | grep -Ei 'sysmode|test|amt|duss|mode' ; echo '--- dumpsys ---'; dumpsys -l 2>/dev/null | grep -Ei 'sysmode|test|amt'",
 "test_domain_cfg": "grep -a -n -B 25 -A 10 'client_domain' /system/etc/dji.json 2>/dev/null | head -80",
 "amt_test_strings": "strings -n 3 /system/bin/dji_amt 2>/dev/null | grep -Ei 'test|diag|1e0|1e7|0x1e|client|domain|role|socket|listen|usb|amt' | head -120",
 "sysmode_binder": "strings -n 5 /system/lib64/libsysmode*.so /system/lib64/libdji_sysmode*.so 2>/dev/null | grep -Ei 'factory|scene|start_factory|ISysMode|set.*mode' | head -80; echo '--- libs ---'; ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'sysmode|mode' | head -20",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=40, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:30]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

