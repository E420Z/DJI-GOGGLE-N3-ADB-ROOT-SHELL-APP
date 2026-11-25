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
 "mb_info": "dji_mb_ctrl -i 2>&1 | head -120; echo EXIT=$?",
 "duml_err_strings": "for f in $(find /system/lib64 /vendor/lib64 -name 'libduml*' 2>/dev/null); do echo \"== $f\"; strings -n 4 $f | grep -Ei 'duss|1002|error|timeout|route|no ack|not.*(found|exist)|unreach|denied|permission' | head -40; done",
 "console_raw_slow": "dji_mb_ctrl -S test -R diag -o 8000000 -g 14 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1 | tail -12; echo EXIT=$?",
 "mb_diag_json": "python3 -c \"import json;d=json.load(open('/system/etc/dji.json'));print(json.dumps(d.get('mb_diagnosis'),indent=1)[:3000])\" 2>/dev/null || grep -a -n -A 30 'mb_diagnosis' /system/etc/dji.json | head -60",
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
    for line in [x for x in txt.splitlines() if x.strip()][:40]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

