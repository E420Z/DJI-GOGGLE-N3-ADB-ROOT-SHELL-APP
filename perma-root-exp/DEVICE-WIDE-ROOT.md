# Device-wide root / ADB — what is possible

Status: **static design.** Nothing here has been run against the charging
goggles. This document defines the boundary between "root everywhere that is
not verity-protected" and "write `/system`", which remains a brick.

## Short answer

- **Yes:** a boot-persistent root ADB shell in `u:r:su:s0` gives broad
  device-wide control: `/data`, `/blackbox`, `/cache`, `/factory_data`,
  `/tmp`, `/sdcard`, runtime `/vendor`, `/proc`/`/sys` where SELinux allows,
  plus execute `/data` binaries.
- **No:** it does **not** make `/system` writable. `/system` is dm-verity
  mode 2; any write there bricks on reboot. There is no safe "write anywhere"
  that includes `/system` without disabling verity or a custom boot image,
  both off-limits.

## Capability matrix

| Path | Root access | Notes |
|---|---|---|
| `/data` | rw | `su` can read/write/execute; some paths deny rename/unlink |
| `/blackbox` | rw | `dji_services` writes here; ~90% full, monitor space |
| `/cache` | rw (root) | ext4 in fstab; SELinux policy to verify |
| `/factory_data` | rw (root) | ext4 in fstab; policy to verify |
| `/tmp` | rw | tmpfs; cleared on reboot |
| `/sdcard` / media | rw | via vold/media_rw; root |
| `/vendor` | rw **at runtime** | raw ext4; remount rw via `dji_services`; AVB coverage unproven; do not put a boot hook there yet |
| `/system` | **ro, read-only** | dm-0 dm-verity mode 2; write = brick; never |
| `/proc`, `/sys` | partial | SELinux-restricted; not arbitrary |
| `/dev/block/*` | read mostly | block writes are off-limits |

## Routes, safest first

### A. Perma-ADB + `su` (recommended)

The `perma-root-exp` boot hook already gives root adbd in `u:r:su:s0`.
From the PC:

```powershell
adb shell id                 # uid=0 in u:r:su:s0
adb shell ls /data
adb shell sh -c 'echo hi > /data/test'
```

This is a device-wide root shell. It can:

- read/write non-verity paths subject to SELinux;
- execute `/data` binaries and scripts;
- start/stop services, set properties, run the patched UI/apps;
- use `adb push/pull` to non-verity paths.

It cannot:

- write `/system`;
- `mount`/bind (`su` has no `sys_admin`);
- relabel files (`chcon` denied).

### B. `dji_services` root shell (privileged file helper)

The same hook can start a root listener in `dji_services` (uid 0). That
domain can:

- write `/data`, `/blackbox`;
- remount `/vendor` rw (the app already does this for theme pushes);
- execute `/system/bin/sh` and `/system/bin` tools;
- **not** execute `/data` binaries.

Use it for `/vendor` remounts and privileged shell work; use `su` for `/data`.

### C. `/data/rootd` daemon (optional control plane)

If a persistent control channel is wanted, a small static aarch64 daemon in
`/data/dji/rootd` can be started from `su`:

```sh
adb shell su 0 /data/dji/rootd --port 5560 --token <random>
```

Design rules:

- bind only to the RNDIS address (`192.168.60.2`) or a localhost socket;
- require a random token on every request;
- path allowlist excluding `/system` and block devices;
- no mount, no relabel, no `/system` write;
- log to `/data/dji/rootd.log`; time-box and stop with the session.

This is convenience only. `adb shell` already gives the same root.

### D. `/vendor/etc/init` `su` service (automatic at boot)

A vendor init service could start `/data/rootd` as `u:r:su:s0` at boot,
giving automatic device-wide root without a host. It is the most powerful
route and the **highest risk**:

- it is a boot-chain change in `/vendor`;
- `/vendor` is raw ext4, but AVB coverage is unproven from the OTA;
- a bad rc/service can bootloop or lose USB;
- recovery may require the bootloader/fastboot, which is locked.

**Do not do this until `/vendor` AVB coverage is proven and a recovery path
exists.** The perma-ADB hook avoids it.

### E. Verity bypass / custom boot

Disabling dm-verity, flashing a custom vbmeta/boot, or `adb remount` on
`/system` is the brick path. The bootloader/AVB is signed; there is no known
unbrick. **Never.**

## What "write anywhere" should mean here

Use this definition:

> Write anywhere **except** verity-protected `/system` and raw block devices.

That covers app data, logs, cache, factory data, media, runtime `/vendor`,
and `/data` binaries. It does not cover `/system`, and it should not try.

## `adb remount` warning

Do **not** run `adb remount` or `mount -o rw,remount /system`. On this device
that is the verity/brick path, not a convenience command.

## Static next steps

1. Verify `su` write permissions for `/cache`, `/factory_data`, and
   `/vendor` from the SELinux policy (static).
2. Determine whether the bootloader verifies `/vendor` (vbmeta/bootarea); if
   it does, route D is off the table.
3. Decide whether route C is useful enough to build; otherwise `adb shell`
   is the control plane.
4. When charged: prove route A (perma-ADB), then test one non-verity write
   path at a time. Never test `/system`.

## Bottom line

- **Device-wide root/ADB: yes**, within SELinux and verity limits.
- **`/system` write: no**, and this design does not attempt it.
- **Safest automatic route:** perma-ADB hook (A) + `su` shell. Route D is a
  later, higher-risk decision.
