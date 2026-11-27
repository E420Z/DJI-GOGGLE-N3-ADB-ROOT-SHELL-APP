# Safety and scope

This project is for the owner's own DJI Goggles N3, on a bench, for UI/theme/
debug development.

**Firmware scope:** tested only on N3 firmware **0900**. Other builds are
untested — vtable/GOT addresses, the USB composition and the vendor OMX
components are build-specific.

## DANGER — never write to `/system`

The goggles run dm-verity in **mode 2 (`restart_on_corruption`)** on `/system`.

- **Do not write to `/system` after disabling verity.** Any write that is not
  followed by a full hash-tree recalculation bricks the device on the next
  reboot (fast bootloop; USB does not enumerate).
- **Do not zero verity metadata.** It makes the partition unmountable.
- There is currently **no known way to unbrick** a device in this state.
- This project normally writes only `/vendor` (flat mods/theme) and
  `/data/local/tmp`. The opt-in `perma-root-exp/` hook additionally writes
  four tiny filenames under `/blackbox/system/sys_perf`; it never modifies
  `/system`, verity metadata, or partitions.

If any instruction or tool asks you to write `/system`, stop.

## Allowed / implemented

- Session-only root shell via the stock `dji_blackbox` log-export RCE.
- ADB enable/disable via the stock USB composition.
- `/vendor` flat-file mods and theme libs, remounted read-write only during a
  push and set back to read-only afterwards.
- Read-only dmabuf capture and a 160×90 live stream.
- In-goggles app windows composited into the live buffer (no frame
  suppression; the real display call is always made).
- Opt-in perma-ADB boot hook (`perma-root-exp/`): `/data` plus tiny
  `/blackbox/system/sys_perf` filenames; no `/system` or `/vendor`.
- One-click recovery to the stock UI.

## Not done

- No `/system` writes, no dm-verity/partition changes.
- No OTP, RPMB, fuse, bootloader, SPI/NVRAM writes.
- No firmware decryption or key extraction.
- No RF transmit, jamming, spoofing, or interception/decryption of third-party
  traffic.
- The **shipped app** has no boot persistence; a power cycle restores stock.
  The opt-in [`perma-root-exp/`](../perma-root-exp/) experiment is separate:
  it uses `/data` and a tiny `/blackbox` filename, never `/system` or
  `/vendor`; see its README and plan.

## Permanent root / ADB experiment

`perma-root-exp/` uses the stock `sys_perf_monitor` root service and a
`/blackbox/system/sys_perf` filename to run `/data/dji/boot-adb.sh` within
~60 s of boot. It switches the USB composition to adb and starts `adbd` with
`--root_seclabel=u:r:su:s0`. It does **not** write `/system` or `/vendor`.

- Test the benign hook first (`touch /data/dji/hook_ok`).
- Kill switch: `touch /data/dji/perma_off`.
- Remove: `host/install_hook.py --remove`; reboot returns the stock USB
  composition.
- The hook is persistent root code execution: keep `boot-adb.sh` minimal and
  log to `/data/dji/perma.log`.
- A bad hook can break USB/UI. Recovery is power-cycle with the hook removed
  or the kill switch present.
- Device-wide limits: root covers non-verity paths; `/system` stays
  read-only. See [`DEVICE-WIDE-ROOT.md`](../perma-root-exp/DEVICE-WIDE-ROOT.md).
  Never run `adb remount` or remount `/system`.
- Why verity/AVB cannot be safely disabled:
  [`VERITY-BYPASS-EXP.md`](../perma-root-exp/VERITY-BYPASS-EXP.md).
- What SELinux permissive would change (and why the current root cannot flip
  it): [`SELINUX-PERMISSIVE.md`](../perma-root-exp/SELINUX-PERMISSIVE.md).

## Recovery

1. App → Connection → **Recover stock UI**.
2. Or power-cycle the goggles.
3. Or `py -3.12 -c "import sys; sys.path.insert(0,'app'); import n3ctl;
   n3ctl.start_stock_ui()"`.

## Legal

Use only on hardware you own and in compliance with local radio/computer-misuse
laws. The authors are not responsible for damage or misuse.
