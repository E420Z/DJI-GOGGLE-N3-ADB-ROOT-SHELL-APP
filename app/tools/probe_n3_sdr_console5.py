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
 "ping_0x43": "-S test -R diag -m 2304 -g 14 -t 0 -s 9 -c 0x43 0002",
 "checkver_0_1": "-S test -R diag -m 2304 -g 14 -t 0 -s 0 -c 1",
 "linktest_00640005": "-S test -R diag -m 2304 -g 14 -t 0 -s 9 -c 0x55 00640005",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
blob=[]
for name, sel in tests.items():
    cmd = "dji_mb_ctrl %s -o 3000000 2>&1 %s; echo EXIT=$?" % (sel, tail)
    print("=====", name)
    txt = n3ctl.run_root(cmd, timeout=30, retries=1)
    blob.append("##### %s\n%s" % (name, txt))
    for line in [x for x in txt.splitlines() if x.strip()][:12]:
        print("  ", line[:200])
open(os.path.join(out, "console_ping.txt"), "w", encoding="utf-8", errors="replace").write("\n".join(blob))
n3ctl.stop_root(log=print)
print("saved")

