import sys, time, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CMDS = r'''echo "=== environ ==="
cat /proc/2780/environ 2>/dev/null | tr "\0" "\n" | head -30
echo "=== adbd strings (ports/props) ==="
strings /system/bin/adbd 2>/dev/null | grep -E "5555|5037|tcp.port|service.adb|ADB_PORT|transport" | head -30
echo "=== adbd size/type ==="
ls -l /system/bin/adbd
echo "=== try setprop tcp port ==="
setprop service.adb.tcp.port 5555; echo setprop_rc=$?
echo "=== try setprop sys.usb.config? (dry: just check prop set perm) ==="
setprop persist.adb.trace_mask x; echo trace_rc=$?
echo "=== selinux denials tail ==="
dmesg 2>/dev/null | grep -iE "avc|denied" | tail -6
echo END_OF_BATCH3
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
        if b'END_OF_BATCH3' in data:
            break
except socket.timeout:
    pass
print(data.decode('utf-8', 'replace')[:6000])
s.close()
