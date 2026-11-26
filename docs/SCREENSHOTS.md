# Safe debug screenshots on the N3

Date: 2026-11-25. Owner's device only. Read-only display capture: no frame
suppression, no radio, no firmware/partition changes.

## What it is

`/vendor/hook_capture.so` is a **capture-only** display mod:

- It interposes `duss_hal_display_push_frame` but **always calls the real
  function**. It never returns early, so it cannot black-screen the UI.
- A background thread polls `/data/local/tmp/n3_capture`. When present, it
  reads the two live 8,294,400-byte `/dmabuf:` surfaces (1920×1080 BGRA) found
  in `/proc/self/maps` and writes them to `/data/local/tmp/screencap0.bin` and
  `screencap1.bin`, then touches `screencap.done`.
- Capture runs on its own thread, so a **static UI (no new frames) is still
  capturable**. The earlier push-frame-only version timed out on idle screens.
- Slot 0 is the front buffer with OSD in testing; slot 1 is the alternate/back
  buffer. Both are saved; slot 0 is reported as the primary screenshot.

Source: `SDR findings/capture-mod/mod.c`
Built: `SDR findings/capture-mod/hook_capture.so` (aarch64, no undefined imports).

## Why a hook is needed

This DJI image has **no `screencap` or `screenrecord`**. The stock Android
screenshot path does not exist. The dmabuf hook is the only working capture
path found, and it is read-only.

## Usage

```
py -3.12 "C:\N3 goggles\SDR findings\tools\debug_screencap.py"
py -3.12 "C:\N3 goggles\SDR findings\tools\debug_screencap.py" --redeploy
py -3.12 "C:\N3 goggles\SDR findings\tools\debug_screencap.py" --loop 2
py -3.12 "C:\N3 goggles\SDR findings\tools\debug_screencap.py" --loop 2 --frames 2
```

- default: one screenshot, then restore stock USB.
- `--redeploy`: re-push the local `.so` and restart the UI to load a new build.
- `--loop N`: continuous capture every N seconds (a ~1 fps USB debug feed)
  until Ctrl+C, then restores stock USB.
- `--frames N`: stop the loop after N captured frames (useful as a burst).
- `--no-start`: require the hook to already be loaded; do not restart the UI.

PNGs land in `SDR findings/debug/<timestamp>/screencap0.png` (primary) and
`screencap1.png`. The raw `.bin` files are kept next to them.

## Verified

- One-shot run: exit 0, both slots pulled, valid 1920×1080 PNGs.
- `--redeploy` run: new `hook_capture.so` (sha256 `39b76cde9520…`) loaded;
  log shows `capture watcher: start` and `capture watcher: pthread_create ret=0`.
- Full-OSD screenshot captured (theme, `E420Z`, `NO Storage`, connection banner,
  battery) with the UI still visible the whole time. See
  `debug/2026-11-25_16-20-10/screencap0.png`.
- Open-menu screenshot captured: sidebar (Status/Album/Transmission/Settings),
  purple focus box, OSD and banner. See
  `debug/2026-11-25_16-22-16/screencap0.png`.
- Loop mode verified: `--loop 2 --frames 2` produced two timestamped captures,
  then restored stock USB (exit 0).

## Safety

- No `/system` writes, no dm-verity/partition, no OTP/RPMB, no bootloader.
- Mod lives in `/vendor` and is loaded with the existing `n3mods.so` loader.
- No boot persistence. `--redeploy` pushes only `hook_capture.so`.
- Capture restores stock USB at the end; the capture flag file is removed.
- The hook is pass-through, so leaving it loaded does not change the display.
- The `--loop` session keeps ADB enabled on purpose and restores it on exit.

## Next

With screenshots working over USB, menu/app UI iteration no longer needs the
risky overlay injection. The remaining display problem is showing a *custom app*
on the goggles; capture does not solve that. Next experiment is the N3-safe
copy-on-push overlay described in `DISPLAY-OVERLAY-N3.md`.
