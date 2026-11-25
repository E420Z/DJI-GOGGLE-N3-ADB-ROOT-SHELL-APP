import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl
base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
scripts = [
 "sdr_shell", "test_rf.sh", "test_sparrow2_link.sh", "test_sparrow2_tsync.sh",
 "test_sparrow2_hw_ver.sh", "test_reset_s2_link.sh", "test_sdrlog_e3t_uart5_link.sh",
 "pro_sparrow2_0.sh", "get_upload_sparrow2_0.sh", "burn_otp_sparrow2_0.sh",
 "prepare_factory_test.sh", "lib_test_utils.sh",
]
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
txt = n3ctl.run_root("cat /system/bin/lib_test_cases.sh", timeout=30, retries=1)
open(os.path.join(out, "lib_test_cases.sh.txt"), "w", encoding="utf-8", errors="replace").write(txt)
blob = []
for s in scripts:
    t = n3ctl.run_root("echo '##### %s'; cat /system/bin/%s 2>&1" % (s, s), timeout=20, retries=1)
    blob.append(t)
    print("=====", s)
    for line in [x for x in t.splitlines() if x.strip()][:40]:
        print("  ", line[:190])
open(os.path.join(out, "factory_scripts_cat.txt"), "w", encoding="utf-8", errors="replace").write("\n".join(blob))
n3ctl.stop_root(log=print)
print("saved")

