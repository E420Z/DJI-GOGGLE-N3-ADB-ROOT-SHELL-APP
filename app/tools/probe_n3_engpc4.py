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
 "engpc_dev_dir": "ls -laR /vendor/etc/engpc 2>/dev/null | head -200; echo '--- files ---'; find /vendor/etc/engpc -maxdepth 3 \\( -type f -o -type l \\) -print -exec cat {} \\; 2>/dev/null | head -260",
 "engpc_strings3": "strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'usage|autotest|vser|acm|tty|com_|config|argv|mode|diag|channel|chnl|start|stop|pc|host' | head -260",
 "engpc_lib2": "strings -n 4 /system/lib64/libengpc_adapt.so 2>/dev/null | grep -Ei 'diag|rf|sdr|iq|adc|test|cmd|port|tty|wcn|calib|factory|usb|vser|autotest' | head -220",
 "amt_factory3": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'factory_debug|factory|cmd|test|audio|ssd|board|rf|sdr|calib|antenna|wifi|bt|sec_|nonce|auth' | head -300",
 "factory_files": "ls -l /factory_data /data/dji/cfg 2>/dev/null | head -80; cat /data/dji/cfg/in_factory 2>/dev/null; cat /factory_data/board_id.txt 2>/dev/null",
 "engpc_help": "dji_engpc -h 2>&1 | head -60",
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
    for line in [x for x in txt.splitlines() if x.strip()][:16]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

