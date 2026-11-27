# Release notes — v1.1.0

Published: 2026-11-27
Tag: `v1.1.0`

**Tested on DJI Goggles N3 firmware 0900 only.** Other firmware builds are
untested: menu/vtable addresses, the USB composition, `dji_glasses` internals
and the vendor OMX components are build-specific.

## Highlights since v1.0.0

- **New control deck** — the CustomTkinter app was replaced by a `pywebview`
  (WebView2) host with an HTML/CSS/JS front-end: eight pages, sliding sidebar,
  command palette, toasts, live status pills and SAFE / EXPERIMENTAL / RISKY
  badges on every action. The Tk app remains as a fallback launcher.
- **Native E420Z row and panel** — a real row in the stock goggles sidebar
  (private data-source vtable copy + Reload hook), opening a stock-styled
  content panel: STATUS / BAND SCAN / DISPLAY TEST / ABOUT / EXIT. No overlay,
  no input hooks; a reboot restores the stock menu.
- **PC Stream** — send this desktop into the goggles over USB. One
  Start/Stop toggle, live encode stats (fps, KB/s, frames), goggles-side
  decode/publish timings, dropped-frame count, and size/fps/quality settings.
  Measured ~12 fps at 1280×720, ~5 fps at 1080p. Frames are dropped to the
  newest to keep latency low, and the OLED screen saver is dismissed
  automatically while streaming.
- **Sparrow2 page** — read-only radio research: firmware inventory, shipped
  console/test tools, and the documented finding that the console is a
  factory-PC tool. Includes an S2 video-capture helper that reports **why** the
  vendor decoder is blocked on this build instead of pretending to work.
- **Live preview and screenshots** — 160×90 … 1920×1080 over USB, plus
  full-resolution dmabuf captures.
- **Mods & UI** — install/remove `/vendor` mods, theme patches, custom
  background, and the frame-injection hook used by PC Stream.
- **SDK** — `sdk/` with the freestanding app API, template, menu example, and
  the in-goggles mod contract (loader `dlsym`, install rules, OMX notes).

## Safety

- **Never writes `/system`.** dm-verity mode 2 means a `/system` write without a
  hash-tree recalculation bricks the device on reboot, with no known unbrick.
- Writes only `/vendor` (remounted read-write for the push, then back to `ro`)
  and `/data/local/tmp`.
- No OTP, RPMB, fuse, bootloader or partition changes.
- Root shell is the stock `dji_blackbox` RCE, session-only; a reboot restores
  stock. **Recover stock UI** is always available.

## Quick start

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 app/webapp.py
```

1. Connection → **Enable ADB** → **Start root**.
2. E420Z → **Start live** for the display mirror.
3. PC Stream → install the **Frame injection (PC stream)** mod, restart the UI,
   then **Start stream**.

## Not included

- `app/assets/libew_gls_stock.so` and `app/assets/dji_glasses_vendor` are DJI
  binaries and are **not** in this repository or release. Theme building needs
  them locally; see the README.
- No firmware images, no keys, no decryption tooling.

## Known limits

- PC Stream is software-decoded on the goggles: 1080p is ~5 fps. The hardware
  H.264 path is documented as proof-of-concept only (`mods/h264/`).
- Sparrow2 raw H.265 capture is blocked on firmware 0900 (the vendor decoder
  needs a `/system` config that must never be written).
- The stock menu row is per-session and disappears on reboot by design.
