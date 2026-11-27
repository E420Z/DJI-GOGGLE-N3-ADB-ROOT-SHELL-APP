# Verity bypass experiment — why `/system` stays read-only

Status: **not attempted.** This document records why a userspace root shell
cannot safely disable dm-verity or AVB, and why the project does not try.
Static analysis only.

## Short answer

Root in `su`/`dji_services` is **above** the protection, not below it. The
goggles check `/system` and the boot chain with keys we do not have. Turning
verity off means changing a signed boot component; this device has no safe
unbrick path.

## The trust chain

```
BootROM / eFuse keys
  -> bootloader (signed)
      -> vbmeta (signed by DJI)
          -> boot / system / vendor partition hashes
              -> dm-verity hash tree for /system
                  -> Android mounts /system read-only
```

Each layer verifies the next **before Android starts**. A root shell inside
Android cannot change what the bootloader already verified.

## Two independent seals

### 1. dm-verity (runtime)

`/system` is mounted from `dm-0`, a device-mapper **dm-verity** target in mode
2 (`restart_on_corruption`).

- Every block is checked against a hash tree.
- The **root hash of that tree is in `vbmeta`**, signed by DJI.
- A mismatch returns an I/O error; mode 2 can restart the device.
- `mount -o rw,remount /system` does not turn verity off. The dm target still
  verifies; the filesystem is still sealed. Forcing writes corrupts the tree.

### 2. AVB / vbmeta (boot-time)

The raw `/system` partition is also covered by Android Verified Boot:

- The bootloader verifies `vbmeta` with a key in the boot chain.
- `vbmeta` contains the hash/verity descriptor for `/system`.
- Even if dm-verity were bypassed at runtime, a modified raw partition fails
  AVB at the next boot. The device may not boot or enumerate USB.

Breaking one seal does not help; the other catches it on reboot.

## Why raw block devices are worse

| Target | Why it is off-limits |
|---|---|
| `/dev/block/by-name/system` | Corrupts AVB + dm-verity; next boot fails |
| `/dev/block/by-name/boot`, `vbmeta` | Signed; a write invalidates the signature; bootloader refuses |
| Partition table / GPT | Can make storage unreadable; no recovery |
| OTP / RPMB / eFuse | One-time programmable; a wrong write is permanent |
| `userdata`, `blackbox`, `cache`, `factory` | Data partitions; writable, not part of verified boot |

Root does not make block writes safe. The block device is storage; the
bootloader’s signature check is the authority.

## What “turning it off” would require

1. **Unlocked bootloader** → `fastboot --disable-verity` / custom `vbmeta`.
   The N3 is a production unit; the bootloader is locked and there is no
   public unlock/EDL/firehose path. A failed boot chain means no USB and no
   recovery.
2. **DJI-signed engineering firmware** with `secure_debug=1` /
   non-production `mp_state`. That is a signed image from DJI; we do not have
   the key.
3. **A kernel/TEE exploit** that patches dm-verity/AVB in memory. That is a
   security exploit, not a supported root path. It would still not survive a
   reboot without re-signing `vbmeta`, and mode 2/AVB can detect it.

There is no userspace command, property, or root shell that safely disables
both layers.

## Do not run

These are the brick-class commands:

```text
adb disable-verity
adb remount
avbctl disable-verification
fastboot --disable-verity
fastboot flash vbmeta / boot / system
dd ... of=/dev/block/by-name/system
dd ... of=/dev/block/by-name/boot
dd ... of=/dev/block/by-name/vbmeta
any OTP / RPMB / eFuse write
```

They are not a shortcut. On this device they are a one-way trip.

## What is safe

| Path | Status |
|---|---|
| `/data` | rw |
| `/blackbox` | rw (tiny hook files; ~90% full) |
| `/cache`, `/factory_data` | likely; live test needed |
| `/tmp`, `/sdcard` | rw |
| `/vendor` | runtime remount only; AVB coverage unproven |
| `/system` | **read-only; never write** |
| block devices, OTP, RPMB | **no** |

“Write anywhere” honestly means **“write anywhere except `/system` and the
verified boot/block-device layer.”**

## Read-only check (when charged)

```sh
getprop ro.boot.flash.locked
getprop ro.boot.verifiedbootstate
getprop ro.boot.veritymode
getprop ro.boot.vbmeta.device_state
```

If `flash.locked=1` and `verifiedbootstate=green`, the device is locked and
AVB-enforcing. If it is `orange`, it is unlocked — but even then, changing
`vbmeta`/`boot` is a deliberate, risky operation, not a casual one.

## Bottom line

- Userspace root gives data partitions and root ADB.
- It does **not** give a writable `/system`.
- Disabling verity/AVB requires the bootloader/signing key or a kernel
  exploit; this device has no safe unbrick path.
- The project stays on the non-verity side.
