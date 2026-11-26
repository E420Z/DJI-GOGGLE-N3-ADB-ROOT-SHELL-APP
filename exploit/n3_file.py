"""n3_file.py - DUML file read/list/push over DJI's libusb0 fork (Windows).

Reads via 00/2a (v2).  Default read receiver 0x3c (dji_sys file server).
Usage:
  py -3.12 n3_file.py read  /system/etc/upgrade.json [recv]
  py -3.12 n3_file.py list  /blackbox [recv]
  py -3.12 n3_file.py raw   0xbc 0x00 0x83 <hexpayload>
"""
import os
import sys, os, time, struct, hashlib, ctypes, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libusb0_dji as L

VID = 0x2CA3
SENDER = 0x2A
T8 = T16 = None


def tables():
    global T8, T16
    # self-contained copy of the DUML CRC tables
    try:
        import crc_tables
        T8, T16 = crc_tables.T8, crc_tables.T16
        return
    except Exception:
        pass
    # fallback: a local toolya checkout, if present
    p = os.path.join(os.path.expanduser("~"), "Downloads", "toolya",
                     "core", "src", "lib.rs")
    t = open(p, encoding='utf-8').read()
    i = t.find('pub const T8'); j = t.find('];', i)
    T8 = [int(x, 16) for x in re.findall(r'0x([0-9A-Fa-f]{2})', t[i:j])][:256]
    i = t.find('pub const T16'); j = t.find('];', i)
    T16 = [int(x, 16) for x in re.findall(r'0x([0-9A-Fa-f]{4})', t[i:j])][:256]


def crc8(b):
    c = 0x77
    for x in b:
        c = T8[(c ^ x) & 0xFF]
    return c


def crc16(b):
    c = 0x3692
    for x in b:
        c = T16[(c ^ x) & 0xFF] ^ (c >> 8)
    return c & 0xFFFF


def frame(body):
    n = len(body) + 6
    hdr = bytes([0x55, n & 0xFF, ((n >> 8) & 3) | 4])
    f = hdr + bytes([crc8(hdr)]) + body
    c = crc16(f)
    return f + bytes([c & 0xFF, c >> 8])


def pkt(sender, dst, seq, cs, cid, payload, ack=0x40):
    return frame(bytes([sender, dst, seq & 0xFF, seq >> 8, ack, cs, cid]) + payload)


def decode(f):
    f = bytes(f)
    if len(f) < 11 or f[0] != 0x55:
        return 'raw %s' % f.hex()
    body = f[4:-2]
    if len(body) < 7:
        return 'raw %s' % f.hex()
    s, d = body[0], body[1]
    seq = body[2] | (body[3] << 8)
    ack = body[4]; cs, cid = body[5], body[6]; pl = body[7:]
    return '%02x->%02x seq=%04x ack=%02x cmd=%02x/%02x len=%d %s' % (
        s, d, seq, ack, cs, cid, len(pl), pl.hex())


def parse_config(buf):
    ifaces = []; cur = None; i = 0
    while i + 2 <= len(buf):
        blen, btype = buf[i], buf[i + 1]
        if blen < 2:
            break
        if btype == 4 and i + blen >= 9:
            cur = [buf[i + 2], buf[i + 5], []]; ifaces.append(cur)
        elif btype == 5 and i + blen >= 7 and cur is not None:
            cur[2].append((buf[i + 2], buf[i + 3]))
        i += blen
    return ifaces


class Duml:
    def __init__(self):
        tables()
        self.lib = L.Libusb0()
        self.buf = b''

    def open(self, want_iface=4):
        lib = self.lib
        target = None
        for d in lib.scan():
            if ('0x%04x' % VID) not in d['filename'].lower():
                continue
            try:
                h = lib.open(d['dev'])
            except Exception:
                continue
            try:
                b = ctypes.create_string_buffer(512)
                n = lib.dll.usb_get_descriptor(h, 2, 0, b, 512)
                ifs = parse_config(b.raw[:n]) if n > 0 else []
            finally:
                lib.close(h)
            for inum, cls, eps in ifs:
                addrs = [a for a, _ in eps]
                if 0x04 in addrs and 0x85 in addrs:
                    target = (d, inum); break
            if target:
                break
        if not target:
            raise SystemExit('no DUML interface found')
        d, inum = target
        self.dev = d
        self.h = lib.open(d['dev'])
        if lib.dll.usb_claim_interface(self.h, inum) < 0:
            lib.dll.usb_set_configuration(self.h, 1)
            if lib.dll.usb_claim_interface(self.h, inum) < 0:
                raise SystemExit('cannot claim iface %d' % inum)
        self.eo, self.ei = 0x04, 0x85
        print('[*] %s iface %d out=0x%02x in=0x%02x' % (d['filename'], inum, self.eo, self.ei))
        hr = self.handshake()
        print('[*] handshake replies: %d' % len(hr))

    def handshake(self):
        INIT = [
            bytes([0x2A, 0x1F, 0x10, 0x27, 0x40, 0x00, 0x01]),
            bytes([0x2A, 0x5C, 0x11, 0x27, 0x40, 0x00, 0x51, 0x04]),
            bytes([0x2A, 0x9C, 0x12, 0x27, 0x42, 0x00, 0x32, 0x00]),
            bytes([0x2A, 0x9C, 0x13, 0x27, 0x42, 0x00, 0x32, 0x31, 0x31, 0x00, 0x00, 0x00]),
        ]
        for b in INIT:
            self.lib.dll.usb_bulk_write(self.h, self.eo, b, len(b), 500)
        for i in range(24):
            b = bytes([0x2A, 0xBC, (0x14 + i) & 0xFF, 0x27, 0x40, 0x00,
                       0x4F, 0x01, 0x00, i, 0x00, 0x00, 0xE8, 0x03, 0x00, 0x00])
            self.lib.dll.usb_bulk_write(self.h, self.eo, b, len(b), 500)
        return self.drain(500)

    def full_init(self):
        """DJI Assistant-style session init (from file_trans.py)."""
        S = 0x2900
        self.send(0x1f, 0, 0x01, b'', S + 0)
        self.send(0x59, 0, 0x01, b'', S + 1)
        self.drain(400)
        self.send(0x5c, 0, 0x51, bytes([0x04, 0x05]), S + 2)
        self.drain(300)
        self.send(0x9c, 0x32, 0x00, bytes([0x0c]), S + 3, ack=0x42)
        self.send(0x9c, 0x32, 0x31, bytes([0x31, 0, 0, 0, 0]), S + 4, ack=0x42)
        self.drain(400)
        for idx in range(14):
            self.send(0xbc, 0, 0x4f,
                      bytes([0x01]) + struct.pack('<H', idx) + b'\x00\x00' + struct.pack('<I', 1000),
                      S + 10 + idx)
        self.drain(500)
        self.send(0x3c, 0, 0x4a, bytes([0xea, 0x07, 0x0b, 0x0b, 0x16, 0x3b, 0x23]), S + 30)
        self.drain(300)
        self.send(0x59, 0, 0xff, b'', S + 31)
        self.drain(300)
        for cid, pl in ((0xe0, b'\x00\x00'), (0xe5, b'\x00\x00'), (0xe9, b'\xff\xff')):
            self.send(0x59, 3, cid, pl, S + 32)
        self.drain(400)
        self.send(0x59, 3, 0xe0, b'\x01\x00', S + 35)
        self.drain(300)
        for idx in range(15):
            self.send(0x59, 3, 0xe1, bytes([0, 0]) + struct.pack('<H', idx), S + 40 + idx)
            self.drain(80)
        self.send(0x59, 3, 0xe2, bytes([0, 0, 1, 0, 0, 0]), S + 60)
        self.send(0x59, 3, 0xe2, bytes([0, 0, 1, 0, 3, 0]), S + 61)
        self.drain(500)

    def send(self, dst, cs, cid, payload, seq, ack=0x40):
        f = pkt(SENDER, dst, seq, cs, cid, payload, ack)
        rc = self.lib.dll.usb_bulk_write(self.h, self.eo, f, len(f), 500)
        if rc < 0:
            raise OSError(self.lib.err(rc))
        return f

    def drain(self, ms, on_frame=None):
        got = []
        end = time.time() + ms / 1000.0
        MAGIC = b'\x21\x12\xad\xde'
        while time.time() < end:
            r = self.lib.read(self.h, self.ei, 4096, 60)
            if r is None:
                continue
            self.buf += r
            while True:
                mi = self.buf.find(MAGIC)
                fi = self.buf.find(b'\x55')
                if mi >= 0 and (fi < 0 or mi < fi):
                    if len(self.buf) < mi + 24:
                        break
                    inner_len = struct.unpack_from('<I', self.buf, mi + 20)[0]
                    if inner_len < 12 or inner_len > 1100:
                        self.buf = self.buf[mi + 4:]
                        continue
                    if len(self.buf) < mi + 24 + inner_len:
                        break
                    fr = self.buf[mi + 24:mi + 24 + inner_len]
                    self.buf = self.buf[mi + 24 + inner_len:]
                    got.append(fr)
                    if on_frame:
                        on_frame(fr)
                    continue
                if fi < 0:
                    if not self.buf:
                        break
                    self.buf = b''
                    break
                if fi:
                    self.buf = self.buf[fi:]
                if len(self.buf) < 12:
                    break
                vl = self.buf[1] | (self.buf[2] << 8)
                whole = vl & 0x3FF
                if whole < 12 or len(self.buf) < whole:
                    if not (vl & 0x300) or whole > 1100:
                        self.buf = self.buf[1:]
                        continue
                    break
                fr = self.buf[:whole]
                self.buf = self.buf[whole:]
                got.append(fr)
                if on_frame:
                    on_frame(fr)
        return got

    def close(self):
        try:
            self.lib.close(self.h)
        except Exception:
            pass


def body_of(fr):
    if len(fr) < 11 or fr[0] != 0x55:
        return None
    return fr[4:-2]


def run_read(d, path, recv=0x5d, timeout=8.0):
    state = {'size': None, 'name': None, 'chunks': {}, 'acks': [], 'tuned': 0}

    def on(fr):
        b = body_of(fr)
        if not b or len(b) < 7:
            return
        s, dd, seq, ack, cs, cid = b[0], b[1], b[2] | (b[3] << 8), b[4], b[5], b[6]
        pl = b[7:]
        if s == 0xbc and cs == 0 and cid == 0x82 and ack == 0x40:
            d.send(recv, 0, 0x82, b'\x00', 0, 0x80)
            return
        if cs != 0 or cid != 0x2a:
            return
        if ack == 0xc0:
            state['acks'].append(pl)
        elif ack == 0x40 and pl:
            if pl[0] == 0x01 and len(pl) >= 8:
                state['size'] = struct.unpack_from('<H', pl, 1)[0]
                nlen = pl[7]
                state['name'] = pl[8:8 + nlen].split(b'\x00')[0].decode('latin1', 'replace')
                if state['tuned'] < 1:
                    state['tuned'] += 1
                    d.send(recv, 0, 0x2a,
                           bytes([0x00, 0xd0, 0x03, 0xa0, 0x0f, 0x01, 0x01]), 0, 0x80)
            elif pl[0] == 0x04 and len(pl) >= 5:
                idx = struct.unpack_from('<I', pl, 1)[0]
                state['chunks'][idx] = pl[5:]
            elif pl[0] == 0x09 and len(pl) >= 7:
                dlen = struct.unpack_from('<I', pl, 3)[0]
                state['recv'] = state.get('recv', 0) + dlen
                d.send(recv, 0, 0x2a,
                       bytes([0x00]) + struct.pack('<I', state['recv']), 0, 0x80)
            else:
                state.setdefault('other', []).append(pl)

    # flush stale traffic from previous sessions
    d.drain(500)
    # block-mode invites then negotiate
    for r in (0x1f, 0x59, 0xb1):
        for k in range(2):
            d.send(r, 0, 0x01, b'', 0x2000 + k)
    d.drain(200, on)
    d.send(recv, 0, 0xea, bytes([0x0a, 0x01, 0x01]), 0x274b)
    d.drain(600, on)
    pb = path.encode()
    payload = bytes([0x08, 0x80]) + pb + b'\x00' * (128 - len(pb)) + b'\x09\x01\x00'
    d.send(recv, 0, 0x2a, payload, 0x274d)
    t0 = time.time()
    while time.time() - t0 < timeout:
        d.drain(400, on)
        if state['size'] and state['chunks']:
            got = len(state['chunks'])
            need = (state['size'] + 975) // 976 if state['size'] else 0
            if got >= need:
                break
        if state['tuned'] < 4:
            state['tuned'] += 1
            d.send(recv, 0, 0x2a,
                   bytes([0x00, 0xd0, 0x03, 0xa0, 0x0f, 0x01, 0x01]), 0, 0x80)
    data = bytearray()
    for idx in sorted(state['chunks']):
        data.extend(state['chunks'][idx])
    state['data'] = data
    return state


def run_list(d, path, recv=0x3c, timeout=5.0):
    frames = []
    def on(fr):
        b = body_of(fr)
        if not b or len(b) < 7:
            return
        s, dd, seq, ack, cs, cid = b[0], b[1], b[2] | (b[3] << 8), b[4], b[5], b[6]
        pl = b[7:]
        if s == recv and cs == 0 and cid == 0x82 and ack == 0x40:
            d.send(recv, 0, 0x82, b'\x00', 0, 0x80)
            return
        if cs == 0 and cid == 0x2a:
            frames.append((ack, pl))
    d.send(recv, 0, 0xea, bytes([0x0a, 0x01, 0x01]), 0x274b)
    d.drain(600, on)
    pb = path.encode()
    payload = bytes([0x06, 0x80]) + pb + b'\x00' * (128 - len(pb)) + b'\x09\x01\x00'
    d.send(recv, 0, 0x2a, payload, 0x274c)
    d.drain(int(timeout * 1000), on)
    return frames


def main():
    a = sys.argv[1:]
    d = Duml(); d.open()
    try:
        if a and a[0] == 'read':
            path = a[1]
            recv = int(a[2], 0) if len(a) > 2 else 0x1f
            if '--init' in a:
                d.full_init()
            st = run_read(d, path, recv, 20.0)
            print('[*] size=%s name=%r got=%d' % (st['size'], st['name'], len(st['data'])))
            if st.get('other'):
                print('[*] other replies:')
                for o in st['other'][:8]:
                    print('    ', o.hex())
            data = bytes(st['data'])
            if data:
                out = 'n3_read.bin'
                open(out, 'wb').write(data)
                print('[*] wrote %s (%d bytes)' % (out, len(data)))
                try:
                    print(data[:1200].decode('utf-8', 'replace'))
                except Exception:
                    pass
        elif a and a[0] == 'list':
            path = a[1]
            recv = int(a[2], 0) if len(a) > 2 else 0x3c
            fr = run_list(d, path, recv)
            for ack, pl in fr:
                print('  ack=0x%02x %s' % (ack, pl.hex()[:400]))
        elif a and a[0] == 'raw':
            dst = int(a[1], 0); cs = int(a[2], 0); cid = int(a[3], 0)
            pl = bytes.fromhex(a[4]) if len(a) > 4 else b''
            d.send(dst, cs, cid, pl, 0x3000)
            for x in d.drain(2500):
                print('  ', decode(x))
        else:
            print(__doc__)
    finally:
        d.close()


if __name__ == '__main__':
    main()
