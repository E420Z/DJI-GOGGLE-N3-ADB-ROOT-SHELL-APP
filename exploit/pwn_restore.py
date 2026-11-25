import sys, time, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CMDS = r'''echo "=== restore baseline (adbd was disabled/stopped) ==="
kill 4127 2>/dev/null; echo kill_our_adbd=$?
stop adbd 2>/dev/null; echo stop_adbd=$?
sleep 1
ps -A | grep adbd; echo grep_rc=$?
getprop init.svc.adbd
echo "=== confirm root shell still alive ==="
id
echo END_OF_BATCH7
'''

s = socket.create_connection(('192.168.60.2', 4444), timeout=6)
s.settimeout(10)
s.sendall(CMDS.encode())
time.sleep(1.5)
data = b''
try:
    while True:
        chunk = s.recv(8192)
        if not chunk:
            break
        data += chunk
        if b'END_OF_BATCH7' in data:
            break
except socket.timeout:
    pass
print(data.decode('utf-8', 'replace')[:3000])
s.close()
