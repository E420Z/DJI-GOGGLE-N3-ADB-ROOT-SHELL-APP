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
 "uart_console_scan": "f=$(ls -t /blackbox/flight*/sdrs/SDRUART-*.log 2>/dev/null | head -1); echo FILE=$f; wc -l \"$f\"; grep -a -Ei 'shell|console|prompt|usage|unknown|invalid|sdr>|cmd list|command' \"$f\" 2>/dev/null | tail -60",
 "uart_iq_scan": "for f in $(ls -t /blackbox/flight*/sdrs/SDRUART-*.log 2>/dev/null | head -6); do echo \"== $f\"; grep -a -Ei 'adc|\\biq\\b|spectrum|fft|sample|raw data|dump' \"$f\" 2>/dev/null | tail -12; done",
 "amt_logs": "ls -la /data/dji/log 2>/dev/null | head -40; echo '--- any factory/debug logs ---'; find /data/dji -maxdepth 3 -type f 2>/dev/null | head -60",
 "wlm_sdr_strings": "for f in $(find /system/lib64 /vendor/lib64 -name 'libwlm*' 2>/dev/null); do echo \"== $f\"; strings -n 5 $f | grep -Ei 'sdr_shell|0x55|cmdset|cmd_id|diag|console|adc|iq|sample|raw|dump|rf' | head -60; done",
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
    for line in [x for x in txt.splitlines() if x.strip()][:30]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

