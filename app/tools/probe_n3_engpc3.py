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
 "engpc_files": "find /vendor/etc/engpc -maxdepth 3 -type f 2>/dev/null | while read f; do echo \"===== $f\"; cat \"$f\"; done; echo '--- dirs ---'; ls -l /vendor/etc/engpc/dev /vendor/etc/engpc/chnl 2>/dev/null",
 "engpc_lib": "find /system /vendor -name 'libengpc_adapt.so' 2>/dev/null; for f in $(find /system /vendor -name 'libengpc_adapt.so' 2>/dev/null); do echo \"===== $f\"; strings -n 4 $f 2>/dev/null | grep -Ei 'diag|rf|sdr|iq|adc|test|cmd|port|tty|wcn|calib|factory|usb' | head -160; done",
 "agent_fds": "p=$(ps -A | grep ' dji_agent$' | tr -s ' ' | cut -d' ' -f2 | head -1); echo PID=$p; [ -n \"$p\" ] && ls -l /proc/$p/fd 2>/dev/null; [ -n \"$p\" ] && echo '--- maps ---' && grep -Ei 'usb|duss|engpc|amt|dji|acm' /proc/$p/maps 2>/dev/null | head -60",
 "agent_strings": "strings -n 4 /system/bin/dji_agent 2>/dev/null | grep -Ei 'factory|amt|engpc|diag|usb|acm|cmd|test|serial|port|pc' | head -200",
 "usb_config": "getprop | grep -Ei 'usb|acm|serial|engpc|factory'; echo '--- configfs ---'; ls -l /config/usb_gadget/g1 2>/dev/null; cat /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration 2>/dev/null",
 "engpc_init": "grep -R -a -i 'engpc\\|libengpc_adapt' /system/etc/init /vendor/etc/init 2>/dev/null | head -120",
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
    for line in [x for x in txt.splitlines() if x.strip()][:16]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

