# Static analysis — perma-root / ADB

Scope: N3 `e3t_zv300`, firmware 0900 (live build `29024`). Static image and
source review; no device execution while this was written.

## 1. The ADB gate at boot

`/system/bin/adbd` is a `disabled` init service:

```
service adbd /system/bin/adbd --root_seclabel=u:r:su:s0
    class core
    disabled
    seclabel u:r:adbd:s0

on property:sys.usb.config=rndis,mass_storage,bulk,acm,adb
    start adbd
```

`adbd` is only started by the exact property value
`rndis,mass_storage,bulk,acm,adb`. `init.e3t.usb.rc` also sets
`service.adb.tcp.port 5555`, but the shipped `adbd` is patched to bind the
local 5037 smart-socket; the root shell is reached over USB, not TCP.

`/system/bin/setup_usb.sh` decides the boot composition from
`/proc/cmdline`:

| cmdline | result |
|---|---|
| `mp_state=production` and `secure_debug=0` (or no `secure_debug`) | `rndis,mass_storage,bulk,acm` (no adb) |
| otherwise | `rndis,mass_storage,bulk,acm,adb` (adb) |

The cmdline is bootloader-owned. `persist.sys.usb.config` is **not consumed**
by this init; `setup_usb.sh` overwrites the runtime value. That is why a
property alone cannot make ADB persistent.

## 2. Runtime root ADB is already proven

The exact runtime sequence (from the project's ADB breakthrough) is:

```sh
setprop service.adb.root 1
setprop service.adb.tcp.port 5555
/system/bin/adb kill-server
setprop sys.usb.config none
setprop sys.usb.config rndis,mass_storage,bulk,acm,adb
```

`adbd` starts from the stock trigger and `setcon()`s to `u:r:su:s0`.
`adb devices` then shows the unit and `adb shell id` is:

```
uid=0(root) gid=0(root) ... context=u:r:su:s0
```

This is the `su` domain, the only subject allowed to execute
`system_data_file` (`/data`). `su` cannot `mount`, bind-mount, `chcon`, or
rename/unlink in some `/data` paths; it can read/execute `/data`.

## 3. The boot hook: `sys_perf_monitor`

`init.e3t.rc` defines:

```
service sys_perf_log /system/bin/sys_perf_monitor
    disabled
    user root
    seclabel u:r:dji_services:s0
```

It is started at boot by `dji_e3t_platform_config.sh` (`start sys_perf_log`).
`/system/etc/sys_perf_common.conf`:

```
enable = 1
log_path = /blackbox/system/sys_perf
compress_threshold = 3
log_rollback_period = 60
```

The compression thread builds:

```c
snprintf(buf, 0x100, "busybox tar -zvcf %s/%s -C %s %s", dir, name, dir, item);
system(buf);
```

`name` is a `ktop.log.*` directory entry and is **not quoted**. A name with
`;` runs a shell command as uid 0 in `u:r:dji_services:s0`.

The safe name uses shell expansion so the name contains no `/`:

```
ktop.log.9999901;x=${PATH:0:1};sh ${x}data${x}dji${x}boot-adb.sh
```

`${PATH:0:1}` is `/`. Four files are created to exceed
`compress_threshold = 3`; the hook fires on the next 60 s compression pass.
`/blackbox/system/sys_perf/{0,1,2,3}` exist; this project uses `/1`.

`dji_services` can write `/blackbox` and execute `/system/bin/sh`, but it
**cannot execute `/data`** (`system_data_file`). So the hook runs a shell
script from `/data` (read by `sh`), not a `/data` binary. The script can run
`/system/bin` tools and set properties.

## 4. Why this gets perma ADB

`boot-adb.sh` runs `usb_adb.sh` from `/data/dji`, which performs the proven
runtime sequence. `dji_services` is allowed to set
`service.adb.root`, `service.adb.tcp.port`, and `sys.usb.config` (the runtime
ADB procedure was executed from this domain). Recheck the exact property-set
policy on the next live run; `usb_adb.sh` auto-reverts if the switch does not
stick. `adbd` starts and becomes `u:r:su:s0`. From there, `adb shell` is root
in `su` and can execute `/data`.

The hook is persistent because:

- `/data/dji/boot-adb.sh` and `/data/dji/usb_adb.sh` survive reboot;
- the four `/blackbox` hook filenames survive reboot until the compressor
  removes them;
- `boot-adb.sh` re-arms the four filenames after each run.

## 5. `/system`, `/vendor`, AVB

- `/system` is mounted from `dm-0` with dm-verity; `androidboot.veritymode`
  is `enforcing`. **Never write it.**
- `vendor.img` (OTA) has **no `AVBf` footer and no ext4 verity feature**;
  `system.img` does. `/vendor` mounts as raw ext4 `ro`. Its AVB coverage is
  not proven from the OTA alone, so this project does not write `/vendor`
  either.
- The perma-root path writes only:
  - `/data/dji/*` (data partition, allowed),
  - four tiny filenames under `/blackbox/system/sys_perf/1` (log partition).
- No `/system`, `/vendor`, boot, OTP, RPMB, or partition writes.

## 6. What is not solved

- The hook fires after boot (up to ~60 s), not at the first second.
- `dji_services` cannot execute `/data`; the first-stage hook cannot start
  `/data` binaries directly. The root `su` adb shell can.
- A fully autonomous `su` boot stage (starting the patched UI/apps without a
  host) needs either a `su` boot trigger or a host-side `adb shell` step.
- The hook is persistent root code execution; a bad `boot-adb.sh` can break
  USB/UI. The kill switch and removal are mandatory.

## 7. Recovery

```sh
# from the session root shell
touch /data/dji/perma_off                 # boot-adb exits on next trigger
rm -f /blackbox/system/sys_perf/1/ktop.log.99999*
```

Or run `host/install_hook.py --kill` / `--remove`. Reboot returns to the
stock `rndis,mass_storage,bulk,acm` composition. If USB is lost, a power
cycle with the hook removed restores stock.

## Local bench notes

The original live probes and the earlier hook prototype are in the owner's
local `findings/` and `ROOT CONFRIM/persist/` trees (not part of this repo).
This folder is self-contained.
