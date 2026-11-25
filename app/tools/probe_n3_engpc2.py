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
 "engpc_dev": "ls -l /vendor/etc/engpc 2>/dev/null; echo '--- dev ---'; cat /vendor/etc/engpc/dev 2>/dev/null; echo '--- other ---'; for f in /vendor/etc/engpc/*; do [ -f $f ] && echo \"===== $f\" && cat $f; done 2>/dev/null",
 "engpc_strings2": "strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'COM_|/dev|tty|baud|diag|open|host|port|modem|wcn|usb|acm|read|write|process|callback|test' | head -300",
 "amt_factory2": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'factory_debug|factory cmd|cmd is|rf|sdr|antenna|wifi|bt|calib|ssd|board|audio|speaker|test|factory' | head -300",
 "amt_all_cmds": "strings -n 3 /system/bin/dji_amt 2>/dev/null | grep -E '^[a-z_]{3,40}$' | head -300",
 "tty_info": "cat /proc/tty/drivers 2>/dev/null; echo '--- acm ---'; ls -l /dev/ttyACM* /dev/ttyGS* /dev/ttyHS* 2>/dev/null; echo '--- usb acm ---'; ls /sys/class/tty 2>/dev/null | head -80",
 "engpc_bin": "ls -l /system/bin/dji_engpc /system/bin/dji_amt; strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'PC|host|usb|acm|diag' | head -120",
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
    for line in [x for x in txt.splitlines() if x.strip()][:16]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

