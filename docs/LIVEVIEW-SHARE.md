# Share Liveview — what it is and how to toggle it

Measured on the owner's N3 (firmware 0900), 2026-11-27. Read-only probing plus
the vendor's own test properties.

## Toggle (no menu needed)

The N3 UI has no Share Liveview switch, but the shipped factory test script
`/system/bin/zv900_app_liveview_test.sh` drives it with two properties:

```sh
setprop test.applv.enable 1
setprop test.applv.func.on 1     # ON
setprop test.applv.func.on 0     # OFF
setprop test.applv.enable 0
```

`dji_sys` owns the state machine (`app_liveview_sm_controller`).

### Measured

```
[ZV300] msg exec succeed! msg(1)
[ZV300] stream statistic : pkg_cnt 700, avg_interval 16.66 ms, avg_fps 60.01
[ZV300] msg exec succeed! msg(2)
```

- **60.01 fps**, steady 16.66 ms pacing, 700 packets in ~12 s.
- Turning it on does **not** change the USB composition and does **not** drop
  ADB/RNDIS. Props return to 0 and the pipeline stops cleanly.

## Transport

`dji_sys` already holds:

```
/dev/aoa                 <- AOA control node
/dev/apple_roleswitch
/dev/applecp
/dev/usb-ffs/bulk4/ep1
/dev/usb-ffs/bulk4/ep2
```

**The goggles is the AOA *host*, not the device.** `dmesg` at boot:

```
(dji_sys) usb_aoa_probe: AOA_CMD_GET_PROTOCOL error:-32
(dji_sys) usb_aoa: probe of 2-1:1.5 failed with error -1
(dji_sys) usbcore: registered new interface driver usb_aoa
(dji_sys) aoa_ioctl: aoa start ok
```

`usb_aoa` registers as a **USB interface driver** (host side) and probes the
attached device's interfaces for the AOA protocol — that is how it puts the
**phone** into accessory mode and streams to it. The goggles' own gadget has no
accessory function (`/config/usb_gadget/g1/functions` lists only
`ffs.adb`, `ffs.bulk*`, `mass_storage`, `rndis`), so it cannot act as an
accessory itself.

Consequences for a PC:

- A PC is always a **host**. Two hosts cannot do AOA with each other, and the
  goggles offers nothing on its device side to switch into accessory mode.
- `libusb0` additionally cannot issue control transfers to the goggles
  (`usb_control_msg` -> `win error: device not functioning`), so even a
  host-side handshake is impossible with the current driver.
- The only hardware that could play the accessory role is a real USB
  device-mode controller (Pi Zero, etc.) — external hardware, out of scope.

## Wi-Fi share is not available either

`wlm_cfg.json` has `"wifi_liveview": {"A": 0, ...}` and the device exposes no
wireless interface at all:

```
ip link  ->  lo, rndis0        (no wlan0, no p2p0)
```

`hostapd`/`wpa_supplicant` binaries exist, but with no `wlan0` there is nothing
to join. `wifi_share_pipe.json` (`LCDC -> wl_encode`) is present but has no
config file (`/etc/wifi_share_cfg.json` is absent from both images).

## What is still true and useful

- The goggles encodes and paces **1080p at 60 fps** for this pipeline — the
  capture ceiling is not the encoder.
- The encoded frames live in the MDC channel `zv900_app_liveview_chn`
  (`app_liveview_pipe.json`), which is the same channel `media_server` feeds.
- Starting the stream is safe and reversible with the properties above.

## Options for PC capture, in order of promise

1. **MDC reader** on `zv900_app_liveview_chn` — needs the C++ channel ABI
   (`libmdcclient.so`); `omx_recordtest` proves the channel works.
2. **Wi-Fi share** — `wifi_share_pipe.json` runs LCDC writeback →
   `OMX.dji.iv_renderer.yuv.wl_encode` → WLM link. Config file
   `/etc/wifi_share_cfg.json` is referenced but absent on this build, so the
   pipe likely needs runtime parameters.
3. **AOA with a different USB driver** (WinUSB/libusbK) — would replace the
   libusb0 binding the root shell depends on. Not worth the risk.
