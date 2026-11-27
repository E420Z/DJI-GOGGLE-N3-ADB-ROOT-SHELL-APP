# Root ADB in `u:r:su:s0` — breakthrough (2026-11-25)

## Result

We obtained an **interactive root shell in the `su` SELinux domain** over USB adb:

```
$ adb shell id
uid=0(root) gid=0(root) groups=0(root),... context=u:r:su:s0
```

`adb devices` showed the goggles as `98765432XXXXXXX device`, and Windows bound
interface `MI_08` as an **ADB Interface** (`USB\VID_2CA3&PID_0020&MI_08`).

This is the domain that was missing: `su` is the **only** subject allowed
`execute` on `system_data_file`:

```
(allow su system_data_file (file (getattr map execute execute_no_trans)))
```

## Exact procedure

The USB adb composition is a stock init path (`/etc/init/init.e3t.usb.rc`);
it is simply not selected at boot on production units.

1. Free the adb smart-socket port **5037**.  `adbd` installs a
   `*smartsocket*` listener there and **aborts** if it is taken:
   ```
   Could not install *smartsocket* listener: Address already in use
   ```
   Kill any on-device `adb` client server first:
   ```
   /system/bin/adb kill-server
   # and any lingering  `adb -L tcp:5037 fork-server server` processes
   ```
2. Set root adb:
   ```
   setprop service.adb.root 1
   setprop service.adb.tcp.port 5555
   ```
3. Switch the USB composition (same sequence `setup_usb.sh` uses at boot):
   ```
   setprop sys.usb.config none
   sleep 2
   setprop sys.usb.config rndis,mass_storage,bulk,acm,adb
   ```
   The `on property:sys.usb.config=...adb` trigger runs `start adbd`, waits for
   `/dev/usb-ffs/adb/ep2`, re-creates `f1..f8`, and writes UDC
   `f9100000.usb`.
4. `adbd` is defined as
   `/system/bin/adbd --root_seclabel=u:r:su:s0`; with
   `service.adb.root=1` it `setcon()`s to `u:r:su:s0`.
5. Host: `adb devices` -> the unit; `adb shell id` -> root in `su`.

The switch script is `../ROOT CONFRIM/adb/usb_adb.sh`. It runs detached,
checks `init.svc.adbd`, `sys.usb.state`, and `ep2`, and reverts to
`rndis,mass_storage,bulk,acm` on failure.

## What `su` can and cannot do

| operation | result |
|---|---|
| read `/data` files (`system_data_file`) | **allowed** (ELF headers read, lib mapped) |
| execute `/data` ELF (`dji_glasses_patched`) | **allowed** |
| write `/data/dji` (create files) | **allowed** |
| `chcon` to `vendor_file` / `system_data_file` | **denied** |
| `mount` / bind mount | **denied** (despite full capabilities) |
| rename / unlink in `/data/ui` | **denied** |

So:

* **No bind-mount over `/system/lib64/libew_gls.so`** from `su`.
* **No relabel** to make `dji_services` execute the patched loader.
* The patched UI must be launched **as `su`**, from `/data/dji`:
  * `/data/dji/dji_glasses_patched` (dlopen `/data/dji/libew_gls.so`)
  * `/data/dji/libew_gls.so` (purple `PlainTextColor a855f7ff`)
  * both SHA-256 verified on device.

`su` is the AOSP root domain; it is **not** `dji_services`, so the open
question is whether the UI can acquire the DJI display/GPU/input devices
from `su`.  That test has not been run yet.

## Failure encountered

`setprop ctl.stop adbd` (a permission test) stopped adbd while the USB
composition still contained `ffs.adb`.  The whole composite device then
disappeared from Windows (no `VID_2CA3`, no RNDIS, no adb).  FunctionFS
appears to take the gadget down when its userspace daemon closes `ep0`.

Recovery: **power-cycle**.  `setup_usb.sh` then selects
`rndis,mass_storage,bulk,acm` (production + `secure_debug=0`), and the
device enumerates normally.  Nothing in this procedure is persistent; a
reboot also clears `service.adb.root` and the adb composition.

## Why this matters

This is a **runtime root shell that can execute `/data`** — the blocker
from `EXEC_CONSTRAINT_2026-11-25.md`.  It does not by itself give
boot-time persistence (adbd is not started, and USB is non-adb at boot),
but it makes live UI development, testing, and patched-binary work possible.

Persistence options still open:

* a boot hook that switches the USB composition to adb (so adb is available
  when a host is attached), then a host-side `deploy` script applies the
  theme;
* finding a boot-time `su` trigger (none yet);
* a `dji_*` domain that can both execute `/data` and access the display
  (none: only `su` has `system_data_file` execute).

## Device files (persist across reboot)

```
/data/dji/usb_adb.sh                 # switch + auto-revert
/data/dji/dji_glasses_patched        # dlopen /data/dji/libew_gls.so
/data/dji/libew_gls.so               # purple PlainTextColor (a855f7ff)
/data/dji/toybox_test                # exec test (can be deleted)
```

`/data/ui/*` still holds the earlier copies; `su` cannot unlink them, so use
the `dji_services` root shell (RCE) if they need cleaning.

## "Root shell did not answer" but the RCE replied `ack=c0`

`ack=c0` only means `dji_blackbox` accepted the log payload. It does **not**
prove the shell bound. Check, in order:

**Start with Connection → Find N3.** It matches the goggles by USB PnP ID
(`USB\VID_2CA3*`), selects the `MI_00` Net adapter by hardware ID, and reads
that adapter's IPv4 plus its ARP neighbours. It never falls back to a non-DJI
adapter, so a `192.168.68.x` subnet is only scanned when Windows says it *is*
the goggles' RNDIS interface. If it reports `no_rndis`, fix the driver/cable
before retrying root; if it reports `no_shell`, the network is fine and the
payload did not bind.

1. **RNDIS address.** The app reads the IPv4 of the `Remote NDIS`/USB adapter
   and probes `x.y.z.2` and `x.y.z.129` on port 4444. If neither answers it
   **sweeps the whole RNDIS /24** (`x.y.z.1-254`), because Windows ICS can hand
   the goggles any DHCP lease. It never scans Wi-Fi/VPN/LAN subnets.
   `N3_HOST` still overrides the scan. Run `ipconfig`: no RNDIS adapter at all
   means RNDIS is down even though the blackbox bulk interface works.
2. **Manual override.** If scanning is blocked or you know the address, set
   `N3_HOST` before launching, then press **Start root** (not Enable ADB, which
   needs root first): `set N3_HOST=192.168.42.129` (cmd) or
   `$env:N3_HOST="192.168.42.129"` (PowerShell). You can also edit `HOST` in
   `app/n3ctl.py`.
3. **Port.** `Test-NetConnection <ip> -Port 4444` must succeed. Refused means
   the payload did not start.
4. **Firmware / handshake.** Only **0900** is tested. On a working 0900 the log
   says `handshake replies: 1`; **`handshake replies: 0` is a red flag** — the
   minimal DUML init was not acknowledged. The app now retries automatically
   after the **full DUML session init** (the DJI-Assistant-style init used for
   file reads) and the shell command tries
   `/system/xbin/busybox`, `/system/bin/busybox`, then `/system/bin/toybox`.
   If both attempts still fail, the 1.09 `dji_blackbox` path likely changed;
   keep that build's `/system/bin/dji_blackbox` for comparison. Do not loop.
5. **Link.** Try another USB port/cable, no hub, and wait ~30 s; RNDIS can take
   a few seconds to re-enumerate.

**APIPA fallback (no DHCP lease).** If the DJI adapter only has a `169.254.x`
address, the app renews DHCP on that adapter. If it still gets nothing, it adds
a temporary `192.168.60.1/24` — then `192.168.42.1/24`, then
`192.168.137.1/24` — **only to the adapter whose PnP ID contains `VID_2CA3`**,
and sweeps that /24 for port 4444. It never touches Wi-Fi/VPN/LAN, and removes
the temporary address on **Stop root** or app exit. This needs administrator;
if Windows refuses, the log says so and you can set the address manually with
`netsh interface ipv4 set address name="Ethernet 3" static 192.168.60.1
255.255.255.0` (revert with `... dhcp`).

## Persistence (experimental)

Runtime root ADB is proven. For a boot-persistent variant, see
[`../perma-root-exp/`](../perma-root-exp/): the stock `sys_perf_monitor`
root service runs `/data/dji/boot-adb.sh` from a `/blackbox` hook filename,
then switches the USB composition to adb and starts `adbd`. It writes only
`/data` and four tiny `/blackbox` filenames — no `/system` or `/vendor`.
Benign hook first; kill switch and removal are documented.
See [`BOOT-ADB.md`](../perma-root-exp/BOOT-ADB.md) for the exact gate and
expected output, and
[`DEVICE-WIDE-ROOT.md`](../perma-root-exp/DEVICE-WIDE-ROOT.md) for the
capability limits.
