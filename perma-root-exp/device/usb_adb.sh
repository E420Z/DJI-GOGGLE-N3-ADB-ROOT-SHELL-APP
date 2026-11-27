#!/system/bin/sh
# usb_adb.sh - switch the USB gadget to the adb composition, verify adbd
# and the gadget state, and auto-revert to the non-adb composition on failure.
#
# Proven on N3 0900: adbd starts with --root_seclabel=u:r:su:s0 and
# "adb shell id" is uid 0 in u:r:su:s0.
#
# Run detached:
#   setsid sh /data/dji/usb_adb.sh >/data/dji/usb_adb.log 2>&1 &
# Or from boot-adb.sh (already root, u:r:dji_services:s0).

LOG=/data/dji/usb_adb.log
USBADB=rndis,mass_storage,bulk,acm,adb
USBNOADB=rndis,mass_storage,bulk,acm

echo "=== $(date) usb_adb start (uptime $(cut -d. -f1 /proc/uptime)s) ===" >> "$LOG"

# Root adbd (this is what gives us the su domain).
setprop service.adb.root 1
setprop service.adb.tcp.port 5555

# adbd installs its *smartsocket* on 5037 and aborts if it is taken.
/system/bin/adb kill-server 2>/dev/null
for p in $(ps -A | grep -E ' adb$' | tr -s ' ' | cut -d' ' -f2); do
    kill -9 "$p" 2>/dev/null
done
sleep 1

# Unbind, then bind with adb (same sequence setup_usb.sh uses at boot).
setprop sys.usb.config none
sleep 2
setprop sys.usb.config "$USBADB"

i=0
ok=0
while [ "$i" -lt 25 ]; do
    sleep 1
    st=$(getprop init.svc.adbd)
    us=$(getprop sys.usb.state)
    if [ "$st" = "running" ] && [ "$us" = "$USBADB" ] && [ -e /dev/usb-ffs/adb/ep2 ]; then
        ok=1
        break
    fi
    i=$((i + 1))
done

if [ -e /dev/usb-ffs/adb/ep2 ]; then ep2=yes; else ep2=no; fi
echo "adbd=$st usb_state=$us ep2=$ep2 ok=$ok waited=${i}s" >> "$LOG"

if [ "$ok" != "1" ]; then
    echo "adb composition failed; reverting to $USBNOADB" >> "$LOG"
    setprop sys.usb.config none
    sleep 2
    setprop sys.usb.config "$USBNOADB"
    sleep 2
    echo "revert state=$(getprop sys.usb.state) adbd=$(getprop init.svc.adbd)" >> "$LOG"
fi

echo "=== $(date) usb_adb end ===" >> "$LOG"
