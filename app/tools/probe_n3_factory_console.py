import os, sys, time
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl
base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
log = []

def rec(title, txt):
    log.append("===== %s =====\n%s" % (title, txt))
    print("=====", title)
    for line in [x for x in str(txt).splitlines() if x.strip()][:30]:
        print("  ", line[:190])

if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
try:
    rec("baseline_ui", n3ctl.ui_state())
    rec("baseline_props", n3ctl.run_root(
        "getprop dji.amt_service; getprop dji.system_service; "
        "ls -l /data/dji/cfg; md5sum /data/us.db", timeout=12, retries=1))
    rec("baseline_console", n3ctl.run_root(
        "timeout 10 /system/bin/sdr_shell help 2>&1", timeout=20, retries=1))

    # ---- enter factory mode (persistent flag) ----
    rec("create_flag", n3ctl.run_root(
        "touch /data/dji/cfg/in_factory; ls -l /data/dji/cfg/in_factory", timeout=10, retries=1))
    rec("restart_amt", n3ctl.run_root(
        "setprop dji.amt_service 0; sleep 2; setprop dji.amt_service 1; sleep 6; "
        "getprop dji.amt_service; pgrep -a dji_amt", timeout=30, retries=1))
    rec("factory_log", n3ctl.run_root(
        "logcat -d -b all 2>/dev/null | grep -Ei 'factory_debug|sys_amt_factory|factory_mode|in_factory|start_factory|test.*host' | tail -80",
        timeout=20, retries=1))
    rec("after_enter_ui", n3ctl.ui_state())

    # ---- read-only console queries ----
    queries = ["help", "?", "version", "info"]
    for q in queries:
        rec("console_%s" % q, n3ctl.run_root(
            "timeout 12 /system/bin/sdr_shell '%s' 2>&1" % q, timeout=25, retries=1))
    rec("console_peer_help", n3ctl.run_root(
        "timeout 12 /system/bin/sdr_shell peer help 2>&1", timeout=25, retries=1))
    rec("console_raw", n3ctl.run_root(
        "dji_mb_ctrl -S test -R diag -m 2304 -o 4000000 -g 14 -t 0 -s 9 -c 0x55 "
        "0064001868656c700d 2>&1 | tail -8", timeout=25, retries=1))
    rec("after_query_ui", n3ctl.ui_state())
finally:
    # ---- recover: remove only the flag we created, restart dji_amt ----
    try:
        rec("recover_remove", n3ctl.run_root(
            "rm -f /data/dji/cfg/in_factory; ls -l /data/dji/cfg", timeout=10, retries=1))
        rec("recover_restart", n3ctl.run_root(
            "setprop dji.amt_service 0; sleep 2; setprop dji.amt_service 1; sleep 4; "
            "getprop dji.amt_service; pgrep -a dji_amt", timeout=30, retries=1))
        rec("recover_ui", n3ctl.ui_state())
        rec("recover_props", n3ctl.run_root(
            "getprop dji.amt_service; getprop dji.system_service; "
            "getprop sys.usb.config; md5sum /data/us.db", timeout=12, retries=1))
        rec("recover_log", n3ctl.run_root(
            "logcat -d -b all 2>/dev/null | grep -Ei 'factory_debug|factory_mode|in_factory' | tail -40",
            timeout=20, retries=1))
    except Exception as exc:
        rec("recover_error", repr(exc))
    n3ctl.stop_root(log=print)

open(os.path.join(out, "factory_console_run.txt"), "w", encoding="utf-8", errors="replace").write("\n".join(log))
print("saved factory_console_run.txt")

