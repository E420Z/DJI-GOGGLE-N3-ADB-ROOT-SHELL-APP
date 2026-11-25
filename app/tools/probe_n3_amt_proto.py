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
 "duss_err_decode": "for f in /system/lib64/libduml_frwk.so /system/lib64/libduml_util.so /system/lib64/libduml_osal.so; do echo \"== $f\"; strings -n 4 $f 2>/dev/null | grep -Ei 'DUSS|1007|1002|route|no.*ack|not.*(register|found|exist)|timeout|send.*fail|host' | head -50; done",
 "amt_proto": "echo '== dji_amt =='; strings -n 4 /system/bin/dji_amt 2>/dev/null | grep -Ei 'AMT|magic|header|factory|cmd|0x[0-9a-fA-F]{2,8}|req|ack|usb|bulk|frame|packet|id' | head -160; echo '== libamt_util =='; strings -n 4 /system/lib64/libamt_util.so 2>/dev/null | grep -Ei 'AMT|magic|header|factory|cmd|0x[0-9a-fA-F]{2,8}|req|ack|usb|bulk|frame|packet|id|sign' | head -120",
 "bulk_cfg": "grep -a -n -B 6 -A 25 'bulk' /system/etc/dji.json 2>/dev/null | head -220",
 "usb_gadget": "ls -l /config/usb_gadget/g1/functions 2>/dev/null; echo '--- strings ---'; for f in /config/usb_gadget/g1/functions/*/; do echo $f; done 2>/dev/null; echo '--- pc svc json ---'; python3 -c \"import json;d=json.load(open('/system/etc/dji.json'));print(json.dumps(d.get('pc_service') or d.get('process',{}).get('pc'),indent=1)[:2000])\" 2>/dev/null",
 "sysmode_service": "service list 2>/dev/null | grep -Ei 'sys|mode|dji' ; echo '--- props ---'; getprop | grep -Ei 'dji\\.|sysmode' | head -60",
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
    for line in [x for x in txt.splitlines() if x.strip()][:34]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

