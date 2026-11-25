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

cmds = {
 "proc_misc": "cat /proc/misc",
 "proc_devices": "cat /proc/devices",
 "test_disp_strings": "grep -a -o -E '.{0,45}(usage|argb|nv12|plane|video|setparam|dump|frame|dispc|display).{0,45}' /system/bin/test_disp 2>/dev/null | head -160",
 "mb_ctrl_strings": "grep -a -o -E '.{0,45}(usage|video|plane|h264|h265|jpeg|uvc|display|frame|simulator|mb_ctrl).{0,45}' /system/bin/dji_mb_ctrl 2>/dev/null | head -200",
 "test_disp_init": "cat /system/bin/test_disp_init.sh 2>/dev/null",
 "media_service_json": "cat /system/etc/dji_media_service.json 2>/dev/null",
 "media_cfg_hits": "grep -a -i -E 'uvc|video_in|plane|h264|h265|jpeg|simulator|mb_ctrl|work_mode' /system/etc/dji_media_service.json /system/etc/media_file2.json /system/etc/media_file2_setting.json 2>/dev/null | head -160",
 "video_in_sysfs": "find /sys -maxdepth 6 \\( -iname '*video_in*' -o -iname '*dji_vtx*' -o -iname '*disp_consumer*' -o -iname '*dji_display*' \\) 2>/dev/null | head -120",
 "v4l_names": "for v in /sys/class/video4linux/video*; do echo -n \"$v \"; cat $v/name 2>/dev/null; done",
 "dmesg_video": "dmesg | grep -Ei 'dji_video_in|video_in|dji_vtx|dji_display|dji_mb_ctrl|test_disp|uvc' | tail -160",
 "logcat_video": "logcat -d -b all 2>/dev/null | grep -Ei 'test_disp|dji_mb_ctrl|video_in|uvc|work_mode|plane 4' | tail -160",
 "misc_names": "for m in /sys/class/misc/*; do [ -e $m ] || continue; echo \"$m $(cat $m/dev 2>/dev/null) $(cat $m/name 2>/dev/null)\"; done 2>/dev/null | head -120",
 "display_feature": "cat /proc/display/feature 2>/dev/null; echo; cat /proc/display/status 2>/dev/null; echo; cat /proc/display/timing 2>/dev/null",
}

if not n3ctl.start_root(log=print):
    raise SystemExit("no root")
for name, cmd in cmds.items():
    print("=====", name)
    try:
        txt = n3ctl.run_root(cmd, timeout=25, retries=1)
    except Exception as exc:
        txt = "ERROR: %s" % exc
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", errors="replace").write(txt)
    for line in [x for x in txt.splitlines() if x.strip()][:8]:
        print("  ", line[:180])
n3ctl.stop_root(log=print)
print("saved")
