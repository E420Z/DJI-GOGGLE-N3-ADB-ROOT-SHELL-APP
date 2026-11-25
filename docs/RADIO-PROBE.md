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

## AP ↔ Sparrow2 control path (DUSS) — checked

- `dji_sdrs_agent` opens `/dev/ttyS1`, the `/bulk/s2_da` channel, the modem
  reset GPIO, `/data/dji_sdrs_agent_pm_*`, and a DUSS socket.
- The AP has a **DUSS message bus**: `/dev/socket`-style endpoints
  `@/duss/mb/0x1c01…0x1f00`, and `dji_mb_ctrl` can send arbitrary messages
  (`-m target_machine -g target_type -t target_idx -s cmd_set -c cmd_id …`).
- `/system/etc/commands.json` lists command IDs for:
  `camera, fc, gimbal, rc, hdvt, vision, djiflight, bvision, ads_b, hms,
  simulator, remote_battery, ui, dm368, special, thirdflight, common, glass,
  extend, wlm, lte, smart_func`.
  **There is no `sdrs_agent`/SDR/IQ/analog command set.**
- `amt_test_cmd` only supports `rpmb_rw <iter>` (RPMB test; dangerous, not RF).
- `dji_engpc` is modem log/boot-mode tooling, not a sample API.
- `/dev/ttyS1` is a log UART; no shell/test prompt was found in SDRUART logs.

**Conclusion:** the AP can talk to the modem/service layer over DUSS, but there
is no documented command for IQ/analog capture. Sending guessed `cmd_set`/
`cmd_id` messages is unsafe (could panic the modem/AP) and is not a supported
path.

## Wi-Fi/BT radio (the other 5 GHz candidate)

- The SoC has SDIO controllers (`f9304000.dwsd0`, `f9300000.dwmmc0`) and
  Wi-Fi/BT board configs (`wifi_board_*.ini`, `bt_configure_*.ini`), plus
  `dji_wifi_cli`.
- But there is **no `wlan0`, no `ieee80211`, no `cfg80211`/`mac80211`, no SDIO
  or PCI device enumerated**, and no wireless debugfs. Wi-Fi is not active in
  this state.
- `dji_wifi_cli` is a station scan/connect CLI, not an SDR/IQ tool.
- So the built-in Wi-Fi/BT path is not an accessible raw-IQ receiver either.

## Memory / RAM / AMT keys — checked

- `/dev/mem` exists, root-only (`crw-------`), and SELinux is enforcing.
  `/dev/kmem`, `/dev/port`, and `/proc/kcore` are absent.
- `/dev/mem` maps **AP DRAM** (`System RAM 0x00000000-0x3b9fffff`), not the C5
  modem’s RAM. The C5 is a separate USB modem; its RAM is not in the AP physical
  map.
- The only AP-visible modem memory path is `s2_sdrdump` — a **crash/RAM dump**
  channel (`AP/CP/L1C/DSP_crash.bin`), off by default and event-triggered. It is
  not a live IQ/sample stream.
- `dji_amt` config is **modem calibration/NVRAM**:
  `modem-pub_key` + `/cali/sdr/nvram/amt.bin` (vendor/original/backup).
  It is the PRAK public key and RF calibration, not an IQ or analog key.
- `dji_amt` strings contain only normal libc/pthread symbols; no key material is
  exposed in the binary.

Reading AP RAM or extracting/using AMT keys would not produce C5 IQ, and
extracting/bypassing keys is a security bypass we will not do.

## Hidden factory surface: MA Channel / AMT

- C5 interface **3** is named **“MA Channel”** (bulk ep `04` out / `84` in,
  1024-byte MPS) and is **unclaimed** (`Driver=none`).
- `dji_sys` holds **three** `/dev/bus/usb/002/002` fds; `dji_amt` is a DUSS
  service (`amt_get_nonce`, `amt_get_sn_from_cmdline`, `duss_event_*`), i.e.
  **nonce/serial manufacturing auth**, not an RF sample API.
- `dji.json` has `start_factory` / `stop_factory` events (`system_service`,
  action `P3`, `lpc_client 0x1C07`) and `amt_service` routes to
  `test`, `vt_gnd`, `ve_gnd`; `test`/`diag` routes exist.
- No `IQ`, `ADC`, `spectrum`, `analog`, or `demod` command names appear in the
  AMT/test/MA configuration. MA is manufacturing/measurement/calibration.

Using MA Channel would require the factory/AMT USB protocol (or triggering
`start_factory` and capturing DUSS), which is undocumented and risky. It is not
a documented IQ source. We have not triggered factory mode or fuzzed MA.

## Exhaustive process/FD audit

Only **one** process has a direct path to the C5:

- `dji_sdrs_agent`: `/dev/bus/usb/002/002` (the C5), `/dev/ttyS1` (modem UART),
  modem reset GPIO, DUSS socket, `/data/dji_sdrs_agent_pm_*`, and
  `libdji_crypto_lib.so` (firmware verification). It uses `usbpri_host_*` /
  `duss_hal_bulk_*`.

Everything else is not the C5 IQ path:

- `dji_wlm`: `/dev/usb-ffs/bulk4/ep1` + `ep2` (PC-facing USB gadget), `/dev/ttyS4`,
  DUSS socket.
- `usb_bulk_raw 1/4/5/6`: PC-facing gadget endpoints (`/dev/usb-ffs/bulk*`).
- `dji_hardlink_drv`: **camera/display** pipeline components
  (`mctf2`, `vtx`, `gdc2`, `ycc`), not the modem.
- `dji_arhome`: `/dev/dji_display` (compositor).
- `dji_mb_ctrl`: generic DUSS message sender; `commands.json` has no
  `sdrs_agent`/SDR/IQ command.
- `amt_test_cmd`: only `rpmb_rw` (RPMB test).
- `dji_engpc`: modem log/boot-mode tooling (not running by default).

No other process holds the C5 USB device or modem UART. The theoretical
alternative — opening `/dev/bus/usb/002/002` and claiming an unbound C5 vendor
interface — has no IQ channel/protocol and could disrupt the modem; not a safe
test.

## C5VRX / “C5” name collision

`Twotoz/C5VRX` is an **ESP32-C5** project, not a DJI C5 modem project:

- Hardware: Seeed Studio XIAO **ESP32-C5** + 6-bit resistor DAC.
- It uses the ESP32-C5’s **own Wi-Fi/5 GHz radio** to take IQ samples and
  demodulate analog 5.8 GHz FPV video to **CVBS PAL/NTSC**.
- It is a tiny receiver board that can be installed **inside** goggles
  (the README shows it in a Fat Shark module bay).

The DJI goggles’ “C5” is a **Sparrow2 modem** (`2ca3:1020`) with encrypted
firmware and no AP readback. The two “C5” names are unrelated.

**Therefore:** a self-contained “only the goggles” analog mod most likely has an
**ESP32-C5 (or similar) receiver board inside the shell**, using the goggles’
antennas and feeding CVBS/video into the goggles’ video input or display. It is
not sampling the DJI O4 modem.

Stock N3 evidence: no Espressif USB/SPI device, no CVBS/PAL/NTSC/TVP/ADV7
decoder in I²C/V4L2, and `/dev/dji_video_in` is a DUSS video-frame input, not
an RF sampler. An internal mod would add its own receiver/decoder hardware.

## Public mod check (Visor / analog)

- The G3 **Visor Mod** (Cosmostreamer) is described as outputting/streaming the
  **original video received from the drone** and PiP/network features. It is not
  evidence of the C5 modem producing analog/IQ samples.
- G3/N3 documentation and community reports say the goggles only support the
  **O4 digital link**; analog needs an added receiver/module or an external
  box. No public teardown shows a C5 IQ/sample interface.
- A self-contained “all inside the goggles” analog mod still has to add a
  receiver board or tap the modem/display hardware. That is a hardware mod, not
  an exposed AP software path.

## If the G3 mod is real

It most likely uses the **display/video plane** (or an added receiver), not the
O4 IQ. Send the link/photos; the key question is whether it connects to a
receiver board or to the display/DSI/video plane.
