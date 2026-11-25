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

ascii_strings = "grep -a -o -E '[ -~]{6,}' %s 2>/dev/null | grep -Ei 'analog|fm|iq|adc|spectrum|demod|tuner|raw|test|factory|mode|rf|sdr' | head -200"
cmds = {
 "test_bins": "ls -l /system/bin/amt_test_cmd /system/bin/dji_engpc /system/bin/dji_amt /system/bin/dji_sec /system/bin/dji_mb_ctrl /system/bin/dji_sdrs_agent /system/bin/test_disp 2>/dev/null; command -v strings; command -v od",
 "mb_ctrl_safe": "cat /system/bin/dji_mb_ctrl_safe.sh 2>/dev/null",
 "autotest_files": "ls -l /system/etc/dji_autotest 2>/dev/null; find /system/etc/dji_autotest -type f 2>/dev/null | head -100",
 "autotest_hits": "grep -a -i -E 'analog|rf|sdr|iq|adc|test|factory|amt|video' -R /system/etc/dji_autotest 2>/dev/null | head -200",
 "etc_test_files": "find /system/etc -maxdepth 3 \\( -iname '*test*' -o -iname '*factory*' -o -iname '*amt*' -o -iname '*autotest*' \\) 2>/dev/null | head -150",
 "dji_json_amt": "grep -a -i -E 'amt|autotest|factory|test_mode|analog|rf|sdr|iq|raw' /system/etc/dji.json 2>/dev/null | head -250",
 "amt_strings": ascii_strings % "/system/bin/amt_test_cmd",
 "engpc_strings": ascii_strings % "/system/bin/dji_engpc",
 "sdr_agent_strings2": ascii_strings % "/system/bin/dji_sdrs_agent",
 "wlm_strings2": ascii_strings % "/system/bin/dji_wlm",
 "mb_ctrl_strings3": ascii_strings % "/system/bin/dji_mb_ctrl",
 "bin_heads": "for f in /system/bin/amt_test_cmd /system/bin/dji_engpc /system/bin/dji_sdrs_agent /system/bin/dji_mb_ctrl; do echo \"== $f\"; head -c 32 $f 2>/dev/null | od -An -tx1 2>/dev/null || head -c 32 $f 2>/dev/null; done",
 "blackbox_analog": "grep -R -a -i -m 20 'analog\\|test mode\\|factory mode' /blackbox 2>/dev/null | head -60",
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
