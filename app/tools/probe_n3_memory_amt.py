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
 "mem_nodes": "id; getenforce; ls -l /dev/mem /dev/kmem /dev/port /proc/kcore 2>/dev/null",
 "mem_sysctls": "for f in /proc/sys/kernel/kptr_restrict /proc/sys/kernel/dmesg_restrict /proc/sys/kernel/perf_event_paranoid /proc/sys/kernel/yama/ptrace_scope; do echo -n \"$f=\"; cat $f 2>/dev/null; done",
 "partitions": "ls -l /dev/block/by-name 2>/dev/null | grep -Ei 'rpmb|otp|key|modem|persist|nv|env|boot|secure' ; echo '--- all count ---'; ls /dev/block/by-name 2>/dev/null | wc -l",
 "amt_bins": "ls -l /system/bin/dji_amt /system/bin/dji_sec /system/bin/amt_test_cmd 2>/dev/null",
 "amt_strings": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'key|rpmb|otp|amt|secure|test|cmd|mode|read|write|auth' | head -160",
 "amt_cfg": "grep -a -i -E 'amt|rpmb|otp|key|secure' /system/etc/dji.json 2>/dev/null | head -160",
 "iomem_reserved": "grep -Ei 'ram|reserved|secure|modem|trust' /proc/iomem 2>/dev/null | head -120",
 "securityfs": "ls -l /sys/kernel/security 2>/dev/null | head -40",
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
    for line in [x for x in txt.splitlines() if x.strip()][:10]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

