import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n3_file as N

d = N.Duml()
d.open()
PAY = bytes([0x01, 0x02, 0x00, 0x03]) + b'foo\x00'


def probe(cs, cid, seq, wait=1.0):
    d.drain(120)
    f = N.pkt(0x0A, 0x5D, seq & 0xffff, cs, cid, PAY, 0x40)
    d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 600)
    out = []

    def on(fr):
        b = N.body_of(fr)
        if not b or len(b) < 7:
            return
        if b[5] == cs and b[6] == cid:
            out.append((b[4], b[7:]))
    d.drain(int(wait * 1000), on)
    return out


try:
    seq = 0x8200
    for cs in (0x19, 0x03, 0x0D, 0x21, 0xEE):
        for cid in (0x30, 0x31, 0x32, 0x49):
            seq += 1
            r = probe(cs, cid, seq)
            txt = ' | '.join('ack=%02x len=%d %s' % (a, len(p), p[:40].hex()) for a, p in r) or 'NO REPLY'
            print('cs=%02x cid=%02x -> %s' % (cs, cid, txt))
finally:
    d.close()
