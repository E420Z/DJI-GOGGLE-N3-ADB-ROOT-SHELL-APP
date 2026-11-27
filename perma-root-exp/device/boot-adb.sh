#!/system/bin/sh
# boot-adb.sh - perma-ADB boot action.
#
# Runs as uid 0 in u:r:dji_services:s0 from the stock sys_perf_monitor hook.
# It only switches USB to the adb composition and starts adbd. It does not
# stop/start the UI.
#
# Persistent state:
#   /data/dji/usb_adb.sh      proven switch script
#   /data/dji/perma.log       log
#   /data/dji/perma_ok        present after a successful adb switch
#   /data/dji/perma_bootid    last boot id that ran
#   /data/dji/perma_off       kill switch; if present, do nothing
#
# Hook files (re-armed below):
#   /blackbox/system/sys_perf/1/ktop.log.999990N;x=${PATH:0:1};sh ${x}data${x}dji${x}boot-adb.sh

LOG=/data/dji/perma.log
USB=/data/dji/usb_adb.sh
HOOKDIR=/blackbox/system/sys_perf/1
USBADB=rndis,mass_storage,bulk,acm,adb

mkdir -p /data/dji 2>/dev/null
echo "=== $(date) boot-adb uptime=$(cut -d. -f1 /proc/uptime) ===" >> "$LOG"

if [ -f /data/dji/perma_off ]; then
    echo "disabled by /data/dji/perma_off" >> "$LOG"
    exit 0
fi

up=$(cut -d. -f1 /proc/uptime)
if [ "$up" -ge 600 ]; then
    echo "late trigger (${up}s); skipping" >> "$LOG"
    exit 0
fi

bootid=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -n "$bootid" ] && [ -f /data/dji/perma_bootid ] &&
   [ "$(cat /data/dji/perma_bootid)" = "$bootid" ]; then
    echo "already ran this boot ($bootid)" >> "$LOG"
    exit 0
fi

if [ ! -f "$USB" ]; then
    echo "missing $USB" >> "$LOG"
    exit 1
fi

sh "$USB" >> "$LOG" 2>&1
st=$(getprop init.svc.adbd)
us=$(getprop sys.usb.state)
echo "adbd=$st usb=$us" >> "$LOG"

if [ "$st" = "running" ] && [ "$us" = "$USBADB" ]; then
    touch /data/dji/perma_ok
    [ -n "$bootid" ] && echo "$bootid" > /data/dji/perma_bootid
    echo "perma-adb OK" >> "$LOG"
else
    echo "adb switch did not stick; stock USB remains" >> "$LOG"
fi

# Re-arm the four hook files; the compressor may delete them after a run.
i=1
while [ "$i" -le 4 ]; do
    touch "$HOOKDIR/ktop.log.999990${i};x=\${PATH:0:1};sh \${x}data\${x}dji\${x}boot-adb.sh" 2>/dev/null
    i=$((i + 1))
done

echo "=== $(date) boot-adb end ===" >> "$LOG"
