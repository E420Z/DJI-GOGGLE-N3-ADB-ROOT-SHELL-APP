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
/dev/aoa                 <- Android Open Accessory node
/dev/apple_roleswitch
/dev/applecp
/dev/usb-ffs/bulk4/ep1
/dev/usb-ffs/bulk4/ep2
```

- The phone link is **AOA**: `dji_sys` strings include `USB_DEV_PATH_FOR_AOA`,
  `cat /sys/devices/virtual/misc/aoa/aoastate`, `OTG ... aoa_state:%d,
  mfi_state:%d`, and it loads `libWorkModeLiveview.so`.
- Accessory presence is detected by an external chip (`ac103_accessory`,
  `ac103_get_accessory_type`), so AOA engages for a **phone**, not a PC.

## Why a PC cannot simply read it

- `libusb0` on this machine cannot issue control transfers to the goggles
  (`usb_control_msg` → `win error: device not functioning`), so the AOA
  handshake (requests 51/52/53) cannot be sent.
- Reading the vendor bulk endpoints yields DUML, not video:
  `55 4d 04 a8 ... 56 33 30 30` = `UM`-framed `V300` status traffic on
  interface 4 / EP `0x85`.
- Other endpoints stayed silent while the stream ran.

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
