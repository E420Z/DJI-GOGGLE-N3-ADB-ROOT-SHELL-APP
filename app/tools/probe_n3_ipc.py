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

cmds = {
 "proc_fds": "for p in $(ps -A | grep -E 'dji_sdrs_agent|dji_wlm|dji_gfsk_agent|dji_mb_ctrl|dji_glasses|dji_media' | tr -s ' ' | cut -d' ' -f2); do echo \"===== PID $p\"; tr '\\0' ' ' < /proc/$p/cmdline; echo; ls -l /proc/$p/fd 2>/dev/null | head -50; done",
 "sockets": "cat /proc/net/unix 2>/dev/null | head -120; echo '--- tcp ---'; cat /proc/net/tcp 2>/dev/null | head -60; echo '--- tcp6 ---'; cat /proc/net/tcp6 2>/dev/null | head -30; echo '--- netstat ---'; netstat -tlnp 2>/dev/null | head -60",
 "mb_ctrl_safe_full": "cat /system/bin/dji_mb_ctrl_safe.sh 2>/dev/null",
 "sdr_agent_strings": "strings -n 4 /system/bin/dji_sdrs_agent 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|cmd|msg|host|port|socket|sparrow|pigeon|uart|bulk' | head -200",
 "mb_ctrl_strings": "strings -n 4 /system/bin/dji_mb_ctrl 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|cmd|msg|host|port|socket|video|plane' | head -200",
 "amt_strings": "strings -n 4 /system/bin/amt_test_cmd 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|cmd|msg|rf|ant|mode' | head -200",
 "engpc_strings": "strings -n 4 /system/bin/dji_engpc 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|cmd|msg|rf|ant|mode' | head -200",
 "libs": "ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'duml|duss|sdr|wlm|gfsk|modem|sparrow|dji' | head -160",
 "lib_strings": "for f in /system/lib64/libduml* /system/lib64/libduss* /system/lib64/libsdrs* /system/lib64/libwlm* /vendor/lib64/libsdrs* /vendor/lib64/libwlm*; do [ -e $f ] || continue; echo \"===== $f\"; strings -n 5 $f 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|spectrum|analog|demod|tuner' | head -80; done",
 "logcat_sdr": "logcat -d -b all 2>/dev/null | grep -Ei 'sdrs_agent|s2_|sparrow|duss|sdr_' | tail -200",
 "sdruart_cmds": "grep -R -a -i -m 60 -E 'help|shell|cmd|test|iq|adc|spectrum|analog|demod' /blackbox/flight*/sdrs 2>/dev/null | head -120",
 "dji_json_procs": "grep -a -i -E 'dji_sdrs_agent|dji_mb_ctrl|dji_wlm|vt_gnd|sdrs_agent' /system/etc/dji.json 2>/dev/null | head -200",
}

if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=35, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:10]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

