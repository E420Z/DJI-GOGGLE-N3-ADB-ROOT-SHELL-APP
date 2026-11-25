#!/system/bin/sh
# Switch the USB gadget to the adb composition, then verify adbd + the
# gadget state; auto-revert to the non-adb composition on failure.
# Run detached:  setsid sh /data/dji/usb_adb.sh >/data/dji/usb_adb.out 2>&1 &
# Boot always reverts (setup_usb.sh sets the non-adb composition on production).
LOG=/data/local/tmp/usb_adb.log
USBADB=rndis,mass_storage,bulk,acm,adb
USBNOADB=rndis,mass_storage,bulk,acm

echo "=== $(date) usb_adb start (uptime $(cut -d. -f1 /proc/uptime)s) ===" >> "$LOG"

# root adbd (this is what gives us the su domain)
setprop service.adb.root 1
setprop service.adb.tcp.port 5555

# adbd installs its *smartsocket* on 5037 and aborts if it is taken.
# Kill any on-device adb client server before starting adbd.
/system/bin/adb kill-server 2>/dev/null
for p in $(ps -A | grep -E ' adb$' | tr -s ' ' | cut -d' ' -f2); do
    kill -9 "$p" 2>/dev/null
done
sleep 1

# unbind, then bind with adb (same sequence the boot script uses)
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
