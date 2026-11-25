import os, sys
APP = r"C:\N3 goggles\ROOT docs\ROOT app"
sys.path.insert(0, APP)
import n3ctl
base = r"C:\N3 goggles\SDR findings\device-evidence"
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
cmds = {
 "mb_ctrl_help": "dji_mb_ctrl -h 2>&1 | head -120",
 "mb_ctrl_all_strings": "strings -n 4 /system/bin/dji_mb_ctrl 2>/dev/null | head -600",
 "duss_libs": "ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'duss|duml|mb|dji' | head -200",
 "etc_mb": "ls -l /system/etc /vendor/etc 2>/dev/null | grep -Ei 'mb|cmd|duss|service|json' | head -120",
 "dji_json_mb": "grep -a -i -E 'mb_ctrl|cmd_set|cmd_id|service_in_json|vt_gnd|sdrs_agent|duss' /system/etc/dji.json 2>/dev/null | head -300",
 "mb_json_files": "find /system/etc /vendor/etc -maxdepth 2 -type f \\( -iname '*mb*' -o -iname '*cmd*' -o -iname '*duss*' -o -iname '*service*' \\) 2>/dev/null | head -120",
}
if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=30, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:10]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")
