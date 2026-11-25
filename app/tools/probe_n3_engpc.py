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
 "engpc_strings": "strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'usage|/dev|tty|COM|port|baud|diag|process|test|rf|sdr|iq|adc|wcn|modem|host|eng_|callback' | head -260",
 "engpc_cfg": "grep -R -a -i -E 'engpc|COM_CP_DIAG|COM_DIAG|DATA_DIAG|DATA_WCN_DIAG|eng_diag' /system/etc/init /system/etc/dji.json /vendor/etc/init 2>/dev/null | head -200",
 "engpc_props": "getprop | grep -Ei 'engpc|eng_diag|diag|factory|amt'; echo '--- tty ---'; ls -l /dev/ttyS* /dev/ttyACM* /dev/ttyUSB* /dev/wwan* 2>/dev/null; echo '--- drivers ---'; cat /proc/tty/drivers 2>/dev/null",
 "engpc_log": "logcat -d -b all 2>/dev/null | grep -Ei 'engpc|eng_diag|COM_DIAG|CP_DIAG|processDiag' | tail -120; dmesg | grep -Ei 'engpc|eng_diag|diag' | tail -80",
 "amt_factory_strings": "strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'FactoryTest|factory|rf|sdr|antenna|wifi|bt|iq|adc|calib|test|cmd' | head -260",
 "amt_cfg2": "grep -a -n -i -B 3 -A 12 'amt_service\\|dji_amt\\|factory' /system/etc/dji.json 2>/dev/null | head -220",
 "init_engpc": "ls -l /system/etc/init | grep -Ei 'engpc|agent|amt|factory'; cat /system/etc/init/dji_agent.rc 2>/dev/null; cat /system/etc/init/dji_amt.rc 2>/dev/null",
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

