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
 "diag_bin_strings": "for f in /system/bin/dji_sdrs_agent /system/bin/dji_sys /system/bin/dji_amt /system/bin/dji_engpc /system/bin/dji_mb_ctrl /system/bin/dji_wlm; do echo \"===== $f\"; strings -n 4 $f 2>/dev/null | grep -Ei 'modem_diag|bitscramb|scramb|sdr_dump|sdr_test|iq|adc|dma|diag|dump|test|ma channel|measure' | head -120; done",
 "diag_cfg_hits": "grep -R -a -i -E 'modem_diag|bitscramb|scramb|sdr_dump|sdr_test|iq|adc|dma|diag' /system/etc/dji.json /system/etc/dji_bb_dls.json /system/etc/commands.json /system/etc/wlm_cfg.json /system/etc/gfsk_agent_cfg.json 2>/dev/null | head -250",
 "diag_logs": "grep -R -a -i -m 80 -E 'modem_diag|bitscramb|scramb|sdr_dump|sdr_test|iq|adc|diag' /blackbox/flight*/sdrs 2>/dev/null | head -160",
 "diag_libs": "ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'diag|sdr|modem|dsp|rf|dma|adc'; for f in /system/lib64/lib*diag* /vendor/lib64/lib*diag* /system/lib64/lib*sdr* /vendor/lib64/lib*sdr*; do [ -e $f ] || continue; echo \"===== $f\"; strings -n 5 $f 2>/dev/null | grep -Ei 'modem_diag|bitscramb|scramb|iq|adc|dma|sdr|dump|test' | head -80; done",
 "sdr_dump_cfg": "grep -a -n -i -A 25 -B 5 'sdr_dump' /system/etc/dji.json 2>/dev/null | head -160",
 "ma_channel_hits": "grep -R -a -i -m 50 -E 'MA Channel|ma_channel|manufactur|antenna|measure' /system/bin /system/etc 2>/dev/null | head -120",
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

