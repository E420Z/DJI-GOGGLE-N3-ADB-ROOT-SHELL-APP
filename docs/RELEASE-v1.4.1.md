# Release notes — v1.4.1

Published: 2026-11-28
Tag: `v1.4.1`
Asset: `N3-ROOT-v1.4.1.zip`

**Tested on DJI Goggles N3 firmware 0900 only.**

## Headline

The PC → Goggles page can now switch the PC to **1920×1080 @ 60 Hz** for
native capture and restore the previous mode when the tunnel stops.

## What changed

### PC display control

- New **PC display** card: current resolution/refresh, **Switch to 1080p** and
  **Restore** buttons.
- New **Auto 1080p** setting (default on): pressing **Start tunnel** saves the
  current PC mode and switches to 1920×1080 @ 60 Hz before capture; **Stop**
  restores the saved mode.
- Buttons are disabled while the tunnel is live; stop first to change manually.
- Backend `pcvideo_display(switch_now, restore)` and a `display` block in
  `pcvideo_info` (`current`, `saved`, `switched`, `auto`, `target`).

### Verified

- Restore: 1920×1080 @ 60 Hz → **2048×1536 @ 240 Hz**.
- Switch: 2048×1536 @ 240 Hz → **1920×1080 @ 60 Hz**; the saved original is
  retained for later restores.
- The PC → Goggles page renders the new card and Auto 1080p checkbox; no
  console errors.

### Unchanged

- 1080p60 hardware tunnel (`vc8000d`/`hevc.vc8000d` → `extra_blending`).
- H.264 ~60 fps at 30 Mbps; H.265 ~60 fps at 20 Mbps.
- Codec/bitrate/cursor, live stats, SDK/docs.
- No `/system`, boot, verity, partition, OTP, fuse or RF changes.

## Notes

- If the PC is already 1920×1080, Start does not switch it; **Restore** remains
  available for the saved original.
- The app must be able to change the display mode (the same API used by
  `app/state/set_display.py`).
