# Plan — perma-root / ADB

Status: **do not run yet.** This is the static plan; wait until the goggles
are charged and the owner is at the bench.

## Phase 0 — preflight (read-only)

1. Goggles booted, stock UI, USB attached.
2. Start the session root shell (Connection → **Start root**).
3. Confirm:
   ```sh
   id                      # uid 0, u:r:dji_services:s0
   ls -ld /blackbox/system/sys_perf /blackbox/system/sys_perf/1
   df -h /data /blackbox
   getprop sys.usb.config  # rndis,mass_storage,bulk,acm
   ```
4. Push the two device scripts:
   ```sh
   mkdir -p /data/dji
   # push perma-root-exp/device/boot-adb.sh -> /data/dji/boot-adb.sh
   # push perma-root-exp/device/usb_adb.sh  -> /data/dji/usb_adb.sh
   chmod 755 /data/dji/boot-adb.sh /data/dji/usb_adb.sh
   ```
5. Make sure there is no stale kill switch:
   ```sh
   rm -f /data/dji/perma_off
   ```

## Phase 1 — benign hook (must pass first)

```powershell
py -3.12 perma-root-exp\host\install_hook.py --benign
```

Wait up to 60 s, then:

```powershell
py -3.12 perma-root-exp\host\install_hook.py --check
```

Expected: `/data/dji/hook_ok` exists (check via the root shell or `--check`).
This proves the filename injection without running `boot-adb.sh`.

Remove the benign hook:

```powershell
py -3.12 perma-root-exp\host\install_hook.py --remove
```

## Phase 2 — arm the adb hook

```powershell
py -3.12 perma-root-exp\host\install_hook.py --arm
```

Then **reboot the goggles** (or wait for the next boot). At boot:

1. `setup_usb.sh` selects the no-adb composition (stock).
2. The sys_perf compressor runs within ~60 s.
3. The hook runs `/data/dji/boot-adb.sh` as root.
4. `boot-adb.sh` runs `usb_adb.sh`; the USB composition becomes
   `rndis,mass_storage,bulk,acm,adb`.
5. `adbd` starts as `u:r:su:s0`.

Verify from the PC:

```powershell
adb kill-server
py -3.12 perma-root-exp\host\verify.py --wait 120
```

Expected:

```
adb devices             -> <serial> device
getprop sys.usb.state   -> rndis,mass_storage,bulk,acm,adb
getprop init.svc.adbd   -> running
getprop service.adb.root-> 1
/data/dji/perma_ok      -> present
id                      -> uid=0(root) ... context=u:r:su:s0
```

If the switch fails, `usb_adb.sh` reverts to `rndis,mass_storage,bulk,acm`;
the device remains usable and the log is in `/data/dji/perma.log` and
`/data/dji/usb_adb.log`.

## Phase 3 — use the root shell

From the PC:

```powershell
adb shell id
adb shell su 0 id          # if the host adb is not already root
adb shell ls -l /data/dji
```

Because `adb shell` is already uid 0 in `su`, it can execute `/data`:

```sh
/data/ui/dji_glasses_patched -g -f   # only if deployed; otherwise stock UI
/data/apps/<your-daemon>
```

Do **not** start `/data` binaries from `boot-adb.sh`: `dji_services` cannot
execute `system_data_file`. The `su` adb shell can.

## Phase 4 — kill / remove / recover

Kill switch (persists across boots until removed):

```powershell
py -3.12 perma-root-exp\host\install_hook.py --kill
```

Resume:

```powershell
py -3.12 perma-root-exp\host\install_hook.py --resume
```

Remove the hook entirely:

```powershell
py -3.12 perma-root-exp\host\install_hook.py --remove
```

Then reboot; `setup_usb.sh` returns the stock no-adb composition.

If USB is lost:

1. Power-cycle the goggles.
2. With the hook removed (or `/data/dji/perma_off` present), stock USB
   returns.
3. `start dji_glasses` restores the stock UI if needed.

## Risk table

| Change | Risk | Mitigation |
|---|---|---|
| Four hook filenames in `/blackbox/system/sys_perf/1` | Tiny flash write; compressor may delete them | `boot-adb.sh` re-arms; `--remove` deletes |
| USB composition switch | Brief re-enumeration; host may drop | `usb_adb.sh` auto-reverts; RNDIS stays in the composition |
| adbd root (`su`) | Root over USB; host authorization | Same PC/key as the proven runtime procedure; stop adbd to close |
| Bad `boot-adb.sh` | Could break USB/UI on every boot | Kill switch, `--remove`, power cycle; keep the script minimal |
| `/system` / `/vendor` | Brick/verity | **Never written**; this path uses `/data` + `/blackbox` only |

## Success criterion

After a cold boot, with no host-side setup beyond `adb`:

- `adb devices` shows the unit;
- `adb shell id` is `uid=0(root)` in `u:r:su:s0`;
- `/data` binaries can be executed from that shell.

That is the perma-root / perma-ADB baseline. A fully host-free patched UI
needs a later `su` boot stage; not part of this phase.
