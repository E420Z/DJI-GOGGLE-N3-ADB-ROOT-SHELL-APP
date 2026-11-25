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
 "dump_strings": "strings -n 4 /system/bin/dji_sdrs_agent 2>/dev/null | grep -Ei 'dump|autotest|test|channel|active|parse|ack|pm_' | head -220",
 "dump_refs": "grep -R -a -l 'sdrs_dump_channel_active\\|sdr_dump\\|dump_v1\\|dump_v0' /system/bin /system/lib64 /vendor/lib64 2>/dev/null | head -80",
 "engpc_strings": "strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'dump|sdr|test|autotest|channel|modem|diag|iq|adc' | head -160",
 "amt_strings2": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'dump|sdr|test|autotest|channel|modem|diag|measure|antenna' | head -160",
 "dump_log": "logcat -d -b all 2>/dev/null | grep -Ei 'autotest|sdr_dump|dump channel|dump_v|sdrs_dump' | tail -120",
 "dump_cfg": "grep -a -n -i -B 3 -A 8 'dump_v0\\|dump_v1\\|autotest\\|sdr_dump' /system/etc/dji_bb_dls.json /system/etc/dji.json 2>/dev/null | head -180",
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
    for line in [x for x in txt.splitlines() if x.strip()][:14]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

