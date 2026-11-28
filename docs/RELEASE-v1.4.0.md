# Release notes — v1.4.0

Published: 2026-11-28
Tag: `v1.4.0`
Asset: `N3-ROOT-v1.4.0.zip`

**Tested on DJI Goggles N3 firmware 0900 only.**

## Headline

PC → goggles is now a first-class **1080p60 hardware tunnel** in the app,
replacing the old JPEG/`fb_receiver` PC Stream route.

## What changed

### PC → goggles 1080p60

- `OMX.dji.video_decoder.avc.vc8000d` (and `hevc.vc8000d`) is tunnelled
  straight into `OMX.dji.iv_renderer.yuv.extra_blending`: no copy, no
  `fb_shared`.
- **H.264: 60.0 fps at 30 Mbps. H.265: 60.1 fps at 20 Mbps.**
- 16 input buffers, 6 MB decoder port, SPS/PPS codec-config, AUD + repeated
  headers.
- Software `avc.ffmpeg` fallback (~40 fps, I420 planar) remains only as a
  fallback.
- Native 1920×1080 capture, Windows cursor drawn, H.264/H.265 selector,
  20/30/40 Mbps, cursor toggle, live stats.

### App

- New **PC → Goggles** page; the old PC Stream/JPEG route, receiver and
  screenshots were removed.
- Live fps, actual bitrate, frames, NVENC encode time, device frames,
  input-buffer returns and drops.
- Start pushes `n3h264live.so`, starts the patched UI with `hook_overlay.so`,
  arms the tunnel; Stop removes the triggers and restores the stock UI.

### SDK / docs

- `sdk/examples/hardware_tunnel/` — full tunnel recipe, buffer ownership,
  codec-config host settings, failure table and `n3_hw_tunnel.h`.
- `docs/PC-TO-GOGGLES.md` now documents the hardware path and H.265 results.
- Removed the obsolete `DisplayEngine` hook warning from the app/docs.

## Verified

App backend on the owner's N3, firmware 0900:

- H.264: **59.6–60.0 fps**, ~29 Mbps, 360 device frames / 6 s, 0 drops.
- H.265: **60.1 fps**, ~19 Mbps, 360 device frames / 6 s, 0 drops.
- Stop returns the stock UI (pid restored).

## Known limits

- Requires the root shell, the mod loader and `hook_overlay.so`.
- Power off the O4 air unit: it shares the display sink and can hold a
  D-Log M colour mode.
- The PC display should be 1920×1080 for unscaled 1080p60; otherwise the sender
  scales/crops.
- The software fallback is ~40 fps at 1080p.
- No `/system`, boot, verity, partition, OTP, fuse or RF changes.

## Safety

- Session-only root; **Recover stock UI** or a power cycle restores stock.
- Writes stay in `/vendor` (module push) and `/data/local/tmp` (runtime).
- No radio transmit or air-link injection.
