# N3 radio/video probe — can we sample the internal 5.8 GHz?

Date: 2026-11-25. Owner's device. **Read-only**: `ls`, `cat`, `getprop`, `dmesg`,
`logcat`, `find`, `grep`. No writes, no service stops, no modem/firmware changes.

Evidence: `device-evidence/2026-11-25_19-42-02/`

## Short answer

- The internal 5.8 GHz path is the **C5 / Sparrow2 modem** (`2ca3:1020`), the same
  family as Goggles 3. The AP can reset/flash it but **cannot read its memory or
  IQ**. There is no `/dev` IQ/ADC/FFT interface.
- The N3 **does** have a real **display video path**: `/proc/display/testcmd`,
  a **video plane 4 (NV12)**, gfx planes 5/6, a writeback plane 7, `test_disp`,
  `/data/disp_fifo`, `/dev/dji_video_in`, `/dev/dji_vtx`, and hardware
  H.264/H.265/JPEG encoders.
- That display path is the likely mechanism behind an “analog mod”: add a
  5.8 GHz **analog receiver**, decode its video, and feed the goggles’ display
  plane. It does **not** sample the O4 modem.

## Radio evidence

```
USB device:          2-1 2ca3:1020 C5
Processes:           dji_sdrs_agent, dji_wlm, dji_gfsk_agent, dji_media_server
Kernel modules:      spi_slave_nrf52810_rx, spi_nrf52810_rx
SPI:                 spi1.0  spi:wl-nrf52810-master
Modem firmware:      /vendor/modem_firmware/sparrow2/{cp,ap,dsp,l1c,scp}.img + nvram
Boot:                fastboot flashes modem-sparrow-* partitions every boot
```

- `dji.json` has `sdrs_agent_service…sdrs_log.channel.sdr_dump` = **status 0**,
  dev `/bulk/s2_sdrdump`, output `dump_store`. That is a modem **RAM/core dump**
  channel, not an IQ stream. G3 research shows it is event-triggered and not
  requestable with known tooling.
- Logs show `handleSDRRole`, `sdr_bw_ifram_recv`, `sdr_ext_info`,
  `sdr_link_info_recv`, `sdr_link_test_recv` — link control/metrics, not samples.
- `gfsk_agent` prints RSSI/packet counters only.
- No RF IIO device: `/sys/bus/iio/devices` is empty; `/proc/misc` contains video
  codecs, not an SDR/ADC.
- The C5 images are `TBIE`/`PRAK` encrypted; the AP has no plaintext and no
  readback. G3’s `MODEM_LOAD_CHAIN.md` documents the same chain.

**Conclusion:** no simple internal IQ/analog sample path. Enabling `sdr_dump`,
flashing modem images, or touching OTP is not a route to IQ and is high risk.

## Display/video evidence

```
/proc/display/plane:
  plane 4 - video: user disabled, no input frame
  plane 5 - gfx0: 1920x1080 argb8888 (dji_glasses)
  plane 6 - gfx1: 1920x1080 argb8888 (CompositorPrivT)
  plane 7 - wrb : 1920x1080 rgb888-i32 (media server / writeback)

/proc/display/testcmd: dumpregs, dumpframe, setparam, print
/dev/dji_display, /dev/dji_video_in, /dev/dji_vtx, /dev/dji_disp_consumer
/system/bin/test_disp, test_disp_init.sh
  test_disp_init.sh: /system/bin/test_disp -p 3 < /data/disp_fifo &
  test_disp usage strings: pixfmt, fps, reserved_lines, plane_id, frame_file_path
Media service: liveview + local/remote playback supported;
  hdmi_dp_in=false, uvc_only=false, simulator=false
```

- The display is MIPI-DSI 1920x1080@60; VOP0 planes are video/NV12, gfx0/gfx1
  ARGB, and a writeback plane.
- `test_disp` can display frames from a FIFO (`/data/disp_fifo`), and there are
  hardware H.264/H.265/JPEG encoders/decoders (`codec_h264e_e3t`,
  `codec_h265e_e3t`, `vc_encoder_pm_jpeg`, `vc_decoder`).
- `dji_video_in` is a platform driver (`video_in_probe success`); likely the
  decoded-video input path, not an RF sampler.

**This is the practical “analog mod” path:** external 5.8 GHz receiver →
composite/decoded video → ARGB/NV12/H.264 → `test_disp`/video plane. The goggles
act as a display; the O4 modem is not involved.

## Deep check of the C5 / modem interfaces

- The C5 exposes **11 vendor interfaces**, all `class ff / subclass 43 / proto 01`,
  two endpoints each. Only `2-1:1.4` is bound to `usbfs`; no interface is a
  standard SDR/ADC/IQ device.
- `sdrs_agent_service…sdr_dump` is `status 0`, output `dump_store`.
  `dji_bb_dls.json` shows the stores are **AP/CP/L1C/DSP crash dumps**
  (`ap_crash_store`, `cp_crash_store`, `l1c_crash_store`, `dsp_crash_store`),
  not sample streams.
- `wlm_cfg.json` has link/video keys (`support_dual_chnl_video`,
  `video_4d_slice_hdr`, `video_5d_slice_hdr`) — digital link configuration, no
  analog/FM/IQ mode.
- `gfsk_agent_cfg.json` has a `gfsk_crash_dump` channel only.
- The SDRUART log is pairing/role/link control (`cp_role`, `sdr state`,
  `pair cmd`), not samples.
- No `analog`, `FM`, `demod`, `tuner`, `IQ`, `ADC`, `FFT`, or `spectrum` mode
  was found in the readable configs. The `dji_sdrs_agent`/`dji_wlm` binaries are
  packed/encrypted enough that their strings are not readable.
- `/dev/dji_video_in` is attached via `duss_hal_attach_video_in` — a **video
  frame input**, not an RF sampler.

**Conclusion (updated):** there is no exposed analog/IQ path from the built-in
5.8 GHz C5 modem. A G3-style “internal-only” analog mod would have to add a
receiver board and feed the **display/video plane**; it cannot be sampling the
O4 modem through the AP.

## Factory/test surface (also checked)

- `/system/bin/amt_test_cmd` (8 KB), `dji_engpc` (137 KB), `dji_mb_ctrl` (18 KB),
  and `dji_sdrs_agent` (385 KB) contain **no readable** `analog`, `FM`, `IQ`,
  `ADC`, `spectrum`, or `demod` strings. `dji_sdrs_agent` is packed/stripped
  enough that even printable-string extraction is empty.
- `/system/bin/dji_mb_ctrl_safe.sh` is an **aging-test lock wrapper** around
  `dji_mb_ctrl`, not an RF mode.
- `/system/etc/dji_autotest/` exists, but has no analog/RF/SDR hits.
- `dji_wlm` readable strings are trace/link (`sdr_enable`, `lte_enable`,
  `test_air_send`), not sample capture.
- SDRUART is pairing/role/link control; `dji_bb_dls.json` stores are crash dumps.
- Public G3 sources also state G3/N3 only support the O4 digital link; analog
  needs an added receiver/module (or a Cosmostreamer-style external box).

## What is *not* present

- No HDMI/DP input (`hdmi_dp_in=false`).
- No UVC input; `uvc_only=false` (and G3’s UVC gadget sends no frames without
  a media-server work-mode switch).
- No `simulator` mode enabled.
- No LTE USB device/`wwan` class on this unit; `lte_service` config exists but
  no LTE hardware was found.

## Safe next steps

1. **Controlled display test** (needs owner approval): use `test_disp` with a
   known ARGB frame on a non-critical plane, with a recovery plan
   (`start_stock_ui` / power-cycle). This proves the display-injection path.
2. **External video pipeline**: external 5.8 GHz receiver → host/Pi → MJPEG/H.264
   → N3 overlay/display plane. We can build the software side with `n3sdk`.
3. **Do not** enable `sdr_dump`, flash modem images, or touch OTP/keys chasing
   IQ. The AP has no readback and the images are encrypted.

## If the G3 mod is real

It most likely uses the **display/video plane** (or an added receiver), not the
O4 IQ. Send the link/photos; the key question is whether it connects to a
receiver board or to the display/DSI/video plane.
