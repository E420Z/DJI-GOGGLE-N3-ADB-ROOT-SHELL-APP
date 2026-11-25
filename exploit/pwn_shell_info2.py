import sys, time, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CMDS = r'''echo "=== adbd cmdline ==="
cat /proc/2780/cmdline; echo
ls -l /proc/2780/exe
echo "=== who owns socket 48952 ==="
for p in /proc/[0-9]*; do ls -l $p/fd 2>/dev/null | grep -q "socket:\[48952\]" && echo "pid=${p#/proc/}"; done
echo "=== adb/usb props ==="
getprop | grep -iE "adb|usb" 
echo "=== usb-ffs ==="
ls -l /dev/usb-ffs/ 2>&1
echo "=== gadget ==="
ls -l /sys/kernel/config/usb_gadget/g1 2>&1 | head
cat /sys/kernel/config/usb_gadget/g1/UDC 2>&1
echo "=== net tcp ==="
cat /proc/net/tcp
echo END_OF_BATCH2
'''

s = socket.create_connection(('192.168.60.2', 4444), timeout=6)
s.settimeout(10)
s.sendall(CMDS.encode())
time.sleep(2.0)
data = b''
try:
    while True:
        chunk = s.recv(8192)
        if not chunk:
            break
        data += chunk
        if b'END_OF_BATCH2' in data:
            break
except socket.timeout:
    pass
print(data.decode('utf-8', 'replace')[:6000])
s.close()
