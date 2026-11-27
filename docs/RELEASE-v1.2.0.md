# Release notes — v1.2.0

Published: 2026-11-27
Tag: `v1.2.0`

**Tested on DJI Goggles N3 firmware 0900 only.** Other firmware builds are
untested: the root payload, menu/vtable addresses, the USB composition,
`dji_glasses` internals and the vendor OMX components are build-specific.

## Highlights since v1.1.0

### Goggles Stream (new page, goggles → PC)

The goggles' **own hardware encoder** is now readable on the PC at full quality
with **no re-encode**:

- **1920×1080, 59–60 fps**, H.264 High from the vc8000e encoder.
- The vendor MDC channel `zv900_app_liveview_chn` is read with
  `OMX.dji.video_reader.avc.mdc`; the stream is served on **TCP 5571**.
- The real **SPS/PPS** (40 bytes) is taken from the vendor encoder and
  prepended, so playback starts immediately.
- The page plays it with **MSE** via ffmpeg (fragmented MP4 over loopback HTTP)
  and shows a telemetry rail: state, resolution, fps, bitrate, frames, dropped,
  latency, session bytes, device-side counters. **Fullscreen** via button,
  double-click or `F`.
- Measured **59–60 fps**, ~2.0–2.2 Mbps on a static UI; a 4 s pull decoded with
  **0 errors**. Verified live in WebView2: `readyState 4`, 1920×1080,
  buffered growing 1.7 → 11.7 s, 718 frames, 0 dropped.

**Bitrate ceiling:** the vendor pipe is fixed at **10 Mbps** by
`bitRate 10000000` in the read-only `/system/etc/app_liveview_pipe.json`. This
project never writes `/system` (dm-verity mode 2, no unbrick), so 10 Mbps is the
shipped maximum. The **60 Mbps** route is research only and **not** in this
release: the raw LCDC YUV channel reads at 59.3 fps and a second vc8000e accepts
a 60 Mbps config, but it needs a separate reader→encoder graph.

Requirements: the root shell **and ffmpeg** on the PC (PATH, `tools\ffmpeg.exe`,
or `FFMPEG=...`). See [`docs/GSTREAM.md`](../docs/GSTREAM.md).

### Root shell: RNDIS address auto-discovery

`ack=c0` from `dji_blackbox` means the payload was accepted, not that the shell
bound. Windows ICS or a different firmware can move the RNDIS subnet, so the app
now:

- reads the IPv4 of the **Remote NDIS / USB** adapter (never Wi-Fi/LAN);
- probes **`x.y.z.2`** and **`x.y.z.129`** on port 4444 and adopts the one that
  answers;
- retries in a throttled background scan, so a shell that appears after USB
  re-enumeration is picked up without blocking the UI;
- still honours **`N3_HOST`** as an explicit override.

Set `N3_HOST` (cmd: `set N3_HOST=192.168.42.129`) before launching if scanning
is blocked. Troubleshooting: [`docs/ADB-ROOT.md`](../docs/ADB-ROOT.md).

### Fixes

- The Goggles Stream page now mounts after the pywebview bridge exists, so it
  polls the real backend instead of latching into mock mode.
- The page script is actually loaded (it was missing from `index.html`).
- “Latency” shows `—` instead of a fake `0 ms`.
- `ui_shot.ps1` accepts relative `-Out` paths.
- Stop → Start rebinds the MP4 stream buffer; app exit clears the vendor
  liveview properties.

## Safety

- **Never writes `/system`.** dm-verity mode 2 means a `/system` write without a
  hash-tree recalculation bricks the device on reboot, with no known unbrick.
- Writes only `/vendor` (remounted read-write for the push, then back to `ro`)
  and `/data/local/tmp`.
- The video-out mod is a **read-only consumer** of a channel `media_server`
  already writes; it never starts/stops the pipeline.
- No OTP, RPMB, fuse, bootloader or partition changes; no radio transmit.
- Root shell is the stock `dji_blackbox` RCE, session-only. **Recover stock UI**
  is always available; a reboot restores stock.

## Quick start

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 app/webapp.py
```

1. Connection → **Start root** (the RNDIS address is found automatically).
2. **Goggles Stream** → **Start stream** (install ffmpeg first).
3. Optional: Connection → **Enable ADB**, then E420Z live preview or PC Stream.

## Known limits

- Goggles Stream is **10 Mbps** maximum (vendor pipe, `/system`), 1080p60.
- 60 Mbps is not shipped; see the research notes in `docs/GSTREAM.md`.
- PC Stream remains software-decoded on the goggles (~12 fps at 720p).
- Sparrow2 raw H.265 capture is blocked on 0900 (vendor decoder needs a
  `/system` config that must never be written).
- Firmware **1.09** is untested; if `ack=c0` but no shell answers on any local
  RNDIS address, the payload target likely changed on that build.
- The stock menu row is per-session and disappears on reboot by design.
