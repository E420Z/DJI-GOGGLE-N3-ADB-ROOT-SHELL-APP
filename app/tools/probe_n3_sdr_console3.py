import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl
base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
tail = "| grep -E 'from machine|error|operation fail|Resp|ack|Send message' | tail -4"
variants = {
 "var_sdrs_agent": "-S sdrs_agent_service -R sdrs_agent",
 "var_wl_manager": "-S wl_manager_service -R wl_manager",
 "var_system": "-S system_service -R system",
 "var_glass": "-S glass_service -R glass",
 "var_default": "",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
blob=[]
for name, sel in variants.items():
    cmd = "dji_mb_ctrl %s -o 3000000 -g 14 -t 0 -s 9 -c 0x55 0064001868656c700d 2>&1 %s; echo EXIT=$?" % (sel, tail)
    print("=====", name, "::", sel or "(default)")
    txt = n3ctl.run_root(cmd, timeout=30, retries=1)
    blob.append("##### %s :: %s\n%s" % (name, sel, txt))
    for line in [x for x in txt.splitlines() if x.strip()][:10]:
        print("  ", line[:190])
open(os.path.join(out, "console_variants.txt"), "w", encoding="utf-8", errors="replace").write("\n".join(blob))
n3ctl.stop_root(log=print)
print("saved")

