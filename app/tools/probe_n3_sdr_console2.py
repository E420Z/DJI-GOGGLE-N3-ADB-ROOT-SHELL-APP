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
 "sdrs_props": "getprop | grep -Ei 'sdrs|sdr|duss|mb' | head -40; echo '--- test svc ---'; ps -A | grep -Ei 'dji_sdrs|dji_mb'",
 # known-good factory link check (S2_UART1 target) with 1s timeout
 "link_check_raw": "dji_mb_ctrl -S test -R diag -o 1000000 -g 14 -t 0 -s 9 -c 0x55 00640005 2>&1; echo EXIT=$?",
 # raw console attempt, show everything
 "console_raw14": "dji_mb_ctrl -S test -R diag -o 2000000 -g 14 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1; echo EXIT=$?",
 "console_raw9": "dji_mb_ctrl -S test -R diag -o 2000000 -g 9 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1; echo EXIT=$?",
 # enumerate: maybe there is a diag route discovery tool
 "mb_json_test": "grep -a -n -A 40 '\"test\"' /system/etc/dji.json 2>/dev/null | head -80",
 "sdruart_after": "f=$(ls -t /blackbox/flight*/sdrs/SDRUART-*.log 2>/dev/null | head -1); echo FILE=$f; tail -n 30 \"$f\" 2>/dev/null",
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

