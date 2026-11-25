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
 "all_fds": "for p in /proc/[0-9]*; do pid=${p##*/}; cmd=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); [ -z \"$cmd\" ] && continue; hits=$(ls -l $p/fd 2>/dev/null | grep -E 'ttyS|dji_|bulk|usb-ffs|/dev/bus/usb|socket'); [ -z \"$hits\" ] && continue; echo \"===== PID $pid $cmd\"; echo \"$hits\"; done",
 "dev_nodes": "ls -l /dev | grep -E 'dji|bulk|ttyS|usb|sdr|modem'; echo '--- misc ---'; cat /proc/misc",
 "misc_class": "ls -l /sys/class/misc 2>/dev/null",
 "hardlink_sys": "find /sys -maxdepth 6 \\( -iname '*hardlink*' -o -iname '*sdrs*' -o -iname '*modem*' -o -iname '*sparrow*' -o -iname '*usbpri*' \\) 2>/dev/null | head -200",
 "hardlink_dmesg": "dmesg | grep -i -E 'hardlink|usbpri|sdrs|sparrow|modem|c5' | tail -200",
 "proc_nodes": "ls /proc | grep -Ei 'dji|sdr|modem|sparrow|usbpri|hardlink'",
 "debug_nodes": "ls /sys/kernel/debug 2>/dev/null | grep -Ei 'dji|sdr|modem|usb|iio|hardlink'; find /sys/kernel/debug -maxdepth 3 \\( -iname '*sdr*' -o -iname '*modem*' -o -iname '*hardlink*' \\) 2>/dev/null | head -120",
 "hardlink_cfg": "grep -a -i -E 'hardlink|usbpri|sdrs|sparrow|modem' /system/etc/dji.json 2>/dev/null | head -250",
 "hardlink_libs": "ls /system/lib64 /vendor/lib64 2>/dev/null | grep -Ei 'hardlink|usbpri|sdr|modem|sparrow'; for f in /system/lib64/libhardlink* /vendor/lib64/libhardlink* /system/lib64/libusbpri* /vendor/lib64/libusbpri*; do [ -e $f ] || continue; echo \"===== $f\"; strings -n 5 $f 2>/dev/null | grep -Ei 'sdr|iq|adc|test|dump|raw|hardlink|usbpri|modem' | head -80; done",
 "sdrs_fds_full": "p=$(ps -A | grep dji_sdrs_agent | tr -s ' ' | cut -d' ' -f2 | head -1); [ -z \"$p\" ] && exit 0; echo PID=$p; ls -l /proc/$p/fd; echo '--- maps ---'; grep -Ei 'usbpri|duss|sdr|modem|hardlink|libdji' /proc/$p/maps | head -80",
 "unix_sockets": "cat /proc/net/unix 2>/dev/null",
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
    for line in [x for x in txt.splitlines() if x.strip()][:12]:
        print("  ", line[:190])
n3ctl.stop_root(log=print)
print("saved")

