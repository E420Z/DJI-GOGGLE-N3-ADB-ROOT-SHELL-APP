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
 "factory_state_files": "ls -la /data/dji/cfg 2>/dev/null; echo '--- sysmode ---'; ls -la /data/sysmode_factory /data/sysmode 2>/dev/null; echo '--- top.cfg ---'; cat /data/dji/cfg/top.cfg 2>/dev/null; echo; echo '--- us.db ---'; ls -l /data/us.db /data/us_factory.db /data/us-bak.db 2>/dev/null; md5sum /data/us.db 2>/dev/null",
 "factory_props_cmdline": "getprop | grep -Ei 'factory|sysmode|boot.mode|usb.config' ; echo '--- cmdline ---'; cat /proc/cmdline",
 "factory_log": "logcat -d -b all 2>/dev/null | grep -Ei 'factory_debug|sys_amt_factory|factory_mode|in_factory|sysmode_factory|start_factory' | tail -80",
 "amt_proc": "p=$(pgrep -f 'dji_amt' | head -1); echo PID=$p; cat /proc/$p/cmdline 2>/dev/null | tr '\\0' ' '; echo; ls -l /proc/$p/fd 2>/dev/null | grep -Ei 'factory|sysmode|us.db|cfg' ; echo '--- threads ---'; ls /proc/$p/task 2>/dev/null | wc -l",
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

