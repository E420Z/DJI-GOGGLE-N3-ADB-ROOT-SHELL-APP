"""root_shell.py - interactive uid-0 shell to the goggles.

Connects to the listener started by spawn_shell.py.

Usage:
    py -3.12 root_shell.py                  # interactive
    py -3.12 root_shell.py -c "id"          # one command, print output
    py -3.12 root_shell.py 192.168.60.2 4444
"""
import socket
import sys
import threading
import time

HOST = '192.168.60.2'
PORT = 4444


def one_shot(cmd):
    s = socket.create_connection((HOST, PORT), timeout=8)
    s.settimeout(8)
    marker = '__CMD_DONE_%d__' % int(time.time())
    s.sendall((cmd + '\necho ' + marker + '\n').encode())
    data = b''
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if marker.encode() in data:
                break
    except socket.timeout:
        pass
    s.close()
    text = data.decode('utf-8', 'replace')
    text = text.replace(marker, '').rstrip()
    print(text)


def interactive():
    s = socket.create_connection((HOST, PORT), timeout=8)
    s.settimeout(None)
    print('[*] connected to %s:%d (root, u:r:dji_services:s0)' % (HOST, PORT))
    print('[*] type commands; Ctrl-C or "exit" to quit')

    def rx():
        try:
            while True:
                d = s.recv(4096)
                if not d:
                    break
                sys.stdout.buffer.write(d)
                sys.stdout.flush()
        except Exception:
            pass

    t = threading.Thread(target=rx, daemon=True)
    t.start()
    try:
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                break
            # the goggles' sh needs LF-only lines; Windows consoles send CRLF
            line = line.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
            if not line.endswith(b'\n'):
                line += b'\n'
            s.sendall(line)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass


def main():
    global HOST, PORT
    a = sys.argv[1:]
    if a and a[0] in ('-c', '--cmd'):
        if len(a) < 2:
            raise SystemExit('usage: root_shell.py -c "<command>"')
        one_shot(a[1])
        return
    if len(a) >= 2:
        HOST = a[0]
        PORT = int(a[1])
    interactive()


if __name__ == '__main__':
    main()
