#!/system/bin/sh
# temporary: restore the stock USB composition and clear adb-root
setprop service.adb.root 0
setprop sys.usb.config none
sleep 2
setprop sys.usb.config rndis,mass_storage,bulk,acm
