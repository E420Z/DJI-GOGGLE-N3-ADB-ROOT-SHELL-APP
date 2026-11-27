# Perma-root / ADB experiment (N3, 0900)

Status: **static design, not armed.** The goggles were charging when this was
written. Nothing in this folder has been run against the device yet.

Goal: a **boot-persistent root ADB shell** (`uid 0`, `u:r:su:s0`) and a
`/data` code-execution path, using only stock services and without writing
`/system` or `/vendor`.

## The path

1. The stock `sys_perf_monitor` service runs as **uid 0** in
   `u:r:dji_services:s0` and compresses files under
   `/blackbox/system/sys_perf/<flight>/`.
2. Its compression command puts the **file name unquoted** into `system()`:
   `busybox tar -zvcf <dir>/<name> -C <dir> <item>`.
3. A file named
   `ktop.log.9999901;x=${PATH:0:1};sh ${x}data${x}dji${x}boot-adb.sh`
   therefore runs `/data/dji/boot-adb.sh` as root.
4. `boot-adb.sh` runs the proven `usb_adb.sh` sequence:
   - `setprop service.adb.root 1`
   - `setprop service.adb.tcp.port 5555`
   - `setprop sys.usb.config none`
   - `setprop sys.usb.config rndis,mass_storage,bulk,acm,adb`
   - adbd starts from the stock init trigger.
5. `adbd` is defined as
   `/system/bin/adbd --root_seclabel=u:r:su:s0`, so `adb shell` is uid 0 in
   the `su` domain. `su` can execute `/data` binaries; `dji_services` cannot.

Boot state is `/data/dji/*` plus four tiny hook filenames under
`/blackbox/system/sys_perf/1`. `/data` survives reboot; the hook re-arms
itself from `boot-adb.sh`.

## Why this is the safe route

- `/system` is dm-verity; it is **never** written.
- The boot cmdline (`mp_state=production`, `secure_debug=0`) makes
  `setup_usb.sh` select the non-adb composition. `persist.sys.usb.config` is
  not consumed by this init. The hook runs **after** boot and switches the
  composition itself.
- `/vendor` is not used. The vendor image is not dm-verity in the OTA, but
  its AVB coverage is unproven; do not touch it.
- `dji_services` can run `/system/bin/sh` and set the USB properties (proven by
  the runtime ADB procedure). `su` (from root adbd) can execute `/data`.
- The switch has an auto-revert: if `sys.usb.state` is not the adb composition
  or `adbd` is not running, it returns to `rndis,mass_storage,bulk,acm`.

## Files

| Path | Purpose |
|---|---|
| `device/boot-adb.sh` | Minimal boot action: adb only, logs, kill switch, re-arm |
| `device/usb_adb.sh` | Proven runtime USB switch, with auto-revert |
| `host/install_hook.py` | `--check`, `--benign`, `--arm`, `--kill`, `--resume`, `--remove` |
| `host/verify.py` | PC-side check: `perma_ok`, `adb devices`, `adb shell id` |
| `STATIC-ANALYSIS.md` | Boot gate, SELinux, hook, AVB, risks |
| `BOOT-ADB.md` | Exact adbd gate, runtime proof, perma hook, expected output |
| `DEVICE-WIDE-ROOT.md` | Capability matrix; what root can write; why `/system` stays read-only |
| `PLAN.md` | Phased benign -> armed test and recovery |

## Safety

- **Static only until the goggles are charged.** Do not run `--arm` first.
- `--benign` first: it only touches `/data/dji/hook_ok`.
- Then `--arm`; the hook fires within ~60 s of boot (threshold 3; four files).
- Kill switch: `touch /data/dji/perma_off` (boot-adb exits).
- Remove: `host/install_hook.py --remove`; reboot returns to the stock USB
  composition.
- The hook is **persistent root code execution**. Keep `boot-adb.sh` minimal;
  never put destructive commands in it.
- No `/system`, no `/vendor`, no boot/OTP/RPMB changes.

## What this gives you

- At boot: adb over USB as `uid 0` in `u:r:su:s0` (root adb).
- From that shell: execute `/data` binaries and scripts, including the
  patched UI or custom daemons.
- The stock UI/display path is untouched; `boot-adb.sh` does not stop
  `dji_glasses`.

## What it does not do

- It does not make the patched UI start automatically. `dji_services` cannot
  execute `/data`; the root `su` adb shell can. A later `su` boot stage can be
  added once the adb path is proven.
- It does not bypass dm-verity or modify `/system`.
- It does not enable ADB at the first second of boot; the hook fires on the
  sys_perf compression interval (up to ~60 s).
