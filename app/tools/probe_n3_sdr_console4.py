import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl
base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
tail = "| grep -E 'from machine|error|operation fail|Resp|ack|data:|Send message' | tail -6"
tests = {
 "m2304_test": "-S test -R diag -m 2304",
 "m0x900_test": "-S test -R diag -m 0x900",
 "m2304_sdrs": "-S sdrs_agent_service -R sdrs_agent -m 2304",
 "m2304_wl": "-S wl_manager_service -R wl_manager -m 2304",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
blob=[]
for name, sel in tests.items():
    cmd = "dji_mb_ctrl %s -o 5000000 -g 14 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1 %s; echo EXIT=$?" % (sel, tail)
    print("=====", name)
    txt = n3ctl.run_root(cmd, timeout=30, retries=1)
    blob.append("##### %s\n%s" % (name, txt))
    for line in [x for x in txt.splitlines() if x.strip()][:12]:
        print("  ", line[:200])
open(os.path.join(out, "console_machine.txt"), "w", encoding="utf-8", errors="replace").write("\n".join(blob))
n3ctl.stop_root(log=print)
print("saved")

