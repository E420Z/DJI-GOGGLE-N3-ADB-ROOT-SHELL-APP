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
 "factory_scripts_find": "for n in test_sparrow2_link.sh test_sparrow2_tsync.sh test_sparrow2_hw_ver.sh test_reset_s2_link.sh test_sdrlog_e3t_uart5_link.sh test_usb_link_e3t_s2.sh test_rf.sh prepare_factory_test.sh; do echo \"===== $n\"; find /system /vendor /data /factory_data -name \"$n\" 2>/dev/null; done",
 "sparrow_scripts_all": "find /system /vendor /data /factory_data -type f \\( -name '*sparrow*' -o -name '*_s2_*' -o -name 'test_rf*' -o -name '*sdrlog*' \\) 2>/dev/null | head -80",
 "amt_test_log": "ls -la /data/dji/log/amt_test 2>/dev/null; echo '--- tail ---'; tail -c 4000 /data/dji/log/amt_test 2>/dev/null",
 "factory_bin_list": "ls -l /system/bin | grep -Ei 'sparrow|s2|sdr|rf|factory|test_' | head -80; echo '--- vendor ---'; ls -l /vendor/bin 2>/dev/null | grep -Ei 'sparrow|s2|sdr|rf|factory|test_' | head -80",
 "s2_nodes": "ls -l /dev | grep -Ei 's2|sparrow|sdr|rf|sdiag|stty_lte|slog' | head -80; echo '--- sysfs ---'; find /sys -maxdepth 4 -iname '*sparrow*' -o -maxdepth 4 -iname '*s2*' 2>/dev/null | head -40",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=45, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:30]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

