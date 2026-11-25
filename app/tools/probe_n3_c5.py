import os, sys, datetime
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import n3ctl

base = os.path.join(APP, "state", "evidence")
if not os.path.isdir(base) or not os.listdir(base):
    raise SystemExit("run probe_n3_radio.py first")
d = sorted([x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))])[-1]
out = os.path.join(base, d)
print("evidence:", out)

pat = "iq|adc|fft|spectrum|analog|demod|tuner|raw|sample|sdr_dump|test_mode|factory|fm_|fm |video_in|vtx|plane"
cmds = {
 "c5_interfaces": "for i in /sys/bus/usb/devices/2-1:*; do [ -e $i ] || continue; echo \"$i class=$(cat $i/bInterfaceClass 2>/dev/null) sub=$(cat $i/bInterfaceSubClass 2>/dev/null) proto=$(cat $i/bInterfaceProtocol 2>/dev/null) eps=$(cat $i/bNumEndpoints 2>/dev/null) driver=$(basename $(readlink $i/driver 2>/dev/null) 2>/dev/null)\"; done",
 "c5_usb_debug": "grep -A 12 -B 2 '2ca3:1020\\|C5' /sys/kernel/debug/usb/devices 2>/dev/null | head -180",
 "sdr_agent_strings": "grep -a -i -o -E '.{0,45}(%s).{0,45}' /system/bin/dji_sdrs_agent 2>/dev/null | head -200" % pat,
 "wlm_strings": "grep -a -i -o -E '.{0,45}(%s).{0,45}' /system/bin/dji_wlm 2>/dev/null | head -200" % pat,
 "gfsk_strings": "grep -a -i -o -E '.{0,45}(%s).{0,45}' /system/bin/dji_gfsk_agent 2>/dev/null | head -200" % pat,
 "mb_ctrl_strings2": "grep -a -i -o -E '.{0,45}(%s).{0,45}' /system/bin/dji_mb_ctrl 2>/dev/null | head -200" % pat,
 "amt_test_strings": "grep -a -i -o -E '.{0,45}(%s).{0,45}' /system/bin/amt_test_cmd 2>/dev/null | head -200" % pat,
 "libs": "ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'duml|sdr|wlm|gfsk|modem|vcodec|media|vop|disp' | head -160",
 "wlm_cfg_hits": "grep -a -i -E 'iq|adc|fft|spectrum|analog|demod|tuner|raw|sdr|dump|link_mode|video' /system/etc/wlm_cfg.json 2>/dev/null | head -220",
 "gfsk_cfg_hits": "grep -a -i -E 'iq|adc|fft|spectrum|analog|demod|tuner|raw|sdr|dump|link_mode|video' /system/etc/gfsk_agent_cfg.json 2>/dev/null | head -160",
 "bb_dls_hits": "grep -a -i -E 'iq|adc|fft|spectrum|analog|demod|tuner|raw|sdr|dump|video' /system/etc/dji_bb_dls.json 2>/dev/null | head -220",
 "dji_json_sdr": "grep -a -i -E 'sdr_dump|sdr_raw|iq|adc|fft|spectrum|analog|demod|tuner|video_in|vtx|plane|raw' /system/etc/dji.json 2>/dev/null | head -250",
 "dt_rf": "find /proc/device-tree -maxdepth 4 \\( -iname '*sdr*' -o -iname '*c5*' -o -iname '*modem*' -o -iname '*rf*' -o -iname '*vtx*' -o -iname '*video*' \\) 2>/dev/null | head -120",
 "modules_rf": "ls /sys/module | grep -Ei 'dji|sdr|modem|nrf|video|vop|disp|rf|adc' | head -120",
 "video_in_params": "find /sys/module/dji_video_in /sys/module/dji_vtx -maxdepth 3 -type f 2>/dev/null | head -60; for f in /sys/module/dji_video_in/parameters/* /sys/module/dji_vtx/parameters/*; do [ -e $f ] && echo \"$f=$(cat $f 2>/dev/null)\"; done",
 "sdruart_tail": "ls -t /blackbox/flight*/sdrs/SDRUART-*.log 2>/dev/null | head -1 | xargs -r tail -n 120",
 "dji_json_video": "grep -a -i -E 'video_in|vtx|plane|disp|media_service|uvc|hdmi|dp_in|simulator|workmode' /system/etc/dji.json 2>/dev/null | head -250",
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
    for line in [x for x in txt.splitlines() if x.strip()][:8]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")
