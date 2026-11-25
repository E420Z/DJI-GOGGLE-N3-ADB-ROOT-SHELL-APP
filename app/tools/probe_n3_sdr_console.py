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
 "sdr_tools": "command -v xxd; command -v dji_mb_ctrl; ls -l /system/bin/sdr_shell /system/bin/dji_mb_ctrl; echo '--- fw sizes ---'; ls -l /vendor/modem_firmware/sparrow2/ | head -40",
 "fw_strings_l1c": "for f in l1c dsp cp scp ap; do echo \\\"===== $f.img\\\"; strings -n 5 /vendor/modem_firmware/sparrow2/$f.img 2>/dev/null | grep -Ei 'iq|adc|dac|spectrum|fft|sample|raw|dump|sdr_shell|help|cmd|diag|test|calib|cal_|rf_|antenna|band|freq' | head -60; done",
 "fw_magic": "for f in /vendor/modem_firmware/sparrow2/*.img /vendor/modem_firmware/sparrow2/*.bin; do printf '%s ' \\\"$f\\\"; head -c 16 \\\"$f\\\" | xxd -p; done 2>/dev/null | head -40",
 "sdr_shell_noarg": "timeout 12 /system/bin/sdr_shell 2>&1 | head -30",
 "sdr_shell_help": "timeout 12 /system/bin/sdr_shell help 2>&1 | head -40",
 "sdr_shell_qmark": "timeout 12 /system/bin/sdr_shell '?' 2>&1 | head -40",
 "sdr_shell_peer_help": "timeout 12 /system/bin/sdr_shell peer help 2>&1 | head -40",
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
    for line in [x for x in txt.splitlines() if x.strip()][:24]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

