# Boot ADB — what actually gates it

Scope: N3 `e3t_zv300`, firmware 0900. Static analysis plus the project's
earlier live ADB proof.

## 1. The adbd service

`/system/etc/init/init.e3t.usb.rc`:

```
service adbd /system/bin/adbd --root_seclabel=u:r:su:s0
    class core
    disabled
    seclabel u:r:adbd:s0
```

It is **disabled** by default. The only trigger in this image is the exact
USB composition:

```
on property:sys.usb.config=rndis,mass_storage,bulk,acm,adb
    start adbd
    wait /dev/usb-ffs/adb/ep2 5
    ...
```

`init_usb2` also sets `service.adb.tcp.port 5555`, but the shipped `adbd` is
patched to bind the local 5037 smart-socket; the root shell used here is over
USB.

## 2. The boot gate: `setup_usb.sh`

`/system/bin/setup_usb.sh` reads `/proc/cmdline`:

| cmdline | boot composition |
|---|---|
| `mp_state=production` and `secure_debug=0` (or no `secure_debug`) | `rndis,mass_storage,bulk,acm` — **no adb** |
| otherwise (engineering/factory or `secure_debug=1`) | `rndis,mass_storage,bulk,acm,adb` — **adb** |

The retail unit is production with `secure_debug=0`, so the boot composition
has no adb. The cmdline is bootloader-owned.

`persist.sys.usb.config=adb` does **not** help: this init does not consume it,
and `setup_usb.sh` overwrites `sys.usb.config` at boot.

## 3. The proven runtime switch

The project obtained a root ADB shell in `u:r:su:s0` at runtime with:

```sh
setprop service.adb.root 1
setprop service.adb.tcp.port 5555
/system/bin/adb kill-server
setprop sys.usb.config none
setprop sys.usb.config rndis,mass_storage,bulk,acm,adb
```

Expected:

```
adb devices             -> <serial> device
adb shell id            -> uid=0(root) ... context=u:r:su:s0
getprop init.svc.adbd   -> running
getprop sys.usb.state   -> rndis,mass_storage,bulk,acm,adb
```

The switch auto-reverts to `rndis,mass_storage,bulk,acm` if adbd or the
functionfs endpoint does not come up.

## 4. Making it boot-persistent

The stock `sys_perf_monitor` service runs as uid 0 in
`u:r:dji_services:s0`. Its compression command puts a `ktop.log.*` file name
unquoted into `system()`. A hook name runs `/data/dji/boot-adb.sh` as root:

```
/blackbox/system/sys_perf/1/ktop.log.9999901;x=${PATH:0:1};sh ${x}data${x}dji${x}boot-adb.sh
```

`boot-adb.sh` runs the proven `usb_adb.sh` sequence. It fires within ~60 s of
boot, after `setup_usb.sh` has selected the no-adb composition. State:

- `/data/dji/boot-adb.sh`, `/data/dji/usb_adb.sh`;
- four hook filenames in `/blackbox/system/sys_perf/1`;
- `/data/dji/perma.log`, `/data/dji/perma_ok`, `/data/dji/perma_bootid`;
- `/data/dji/perma_off` kill switch.

No `/system` or `/vendor` write. See `PLAN.md` and `README.md`.

## 5. What boot ADB does not do

- It is not instant: up to ~60 s after boot.
- It does not make `/system` writable; dm-verity remains.
- It does not start a `/data` binary from `dji_services`; that domain cannot
  execute `system_data_file`. The root `su` adb shell can.
- It does not bypass the bootloader cmdline or modify the boot image. It runs
  a stock root service **after** boot.

## 6. Verification and recovery

```powershell
adb kill-server
py -3.12 perma-root-exp\host\verify.py --wait 120
```

Recovery:

```powershell
py -3.12 perma-root-exp\host\install_hook.py --kill     # stop future runs
py -3.12 perma-root-exp\host\install_hook.py --remove   # delete hooks
```

Then reboot: the stock no-adb composition returns. If USB is lost, power-cycle
with the hook removed or `perma_off` present.
