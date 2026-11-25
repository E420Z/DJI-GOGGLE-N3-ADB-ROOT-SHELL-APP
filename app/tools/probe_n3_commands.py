import os, sys
APP = r"C:\N3 goggles\ROOT docs\ROOT app"
sys.path.insert(0, APP)
import n3ctl
base = r"C:\N3 goggles\SDR findings\device-evidence"
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
cmds = {
 "commands_json": "cat /system/etc/commands.json 2>/dev/null",
 "commands_hits": "grep -a -i -E 'sdr|iq|adc|test|dump|raw|spectrum|analog|video|plane|sparrow|modem|rf|cmd_set|cmd_id' /system/etc/commands.json 2>/dev/null | head -300",
 "command_files": "find /system/etc /vendor/etc -maxdepth 2 -type f \\( -iname '*command*' -o -iname '*cmd*' -o -iname '*test*' \\) 2>/dev/null | head -150",
 "mb_help_full": "dji_mb_ctrl -h 2>&1",
 "commands_meta": "ls -l /system/etc/commands.json /vendor/etc/commands.json 2>/dev/null; head -c 64 /system/etc/commands.json 2>/dev/null | od -An -tc 2>/dev/null",
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
    for line in [x for x in txt.splitlines() if x.strip()][:12]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")
