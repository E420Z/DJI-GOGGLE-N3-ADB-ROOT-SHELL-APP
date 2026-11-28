# n3sdk — in-goggles N3 app SDK (v0.1)

A tiny freestanding SDK for apps/menus that draw over the N3 UI **without
black-screening it**. Proven on the owner's device on 2026-11-25.

## How it works

- The app is a preload `.so` loaded by `n3mods.so` into `dji_glasses`.
- While `/data/local/tmp/n3_app_on` exists, the app draws into a double-buffered
  offscreen canvas. The published canvas is blitted into the live dmabuf:
  - inside a `duss_hal_display_push_frame` detour, right before the real push
    (primary path, avoids compositor overwrite/flicker);
  - from the app thread as a fallback for static screens.
- The detour **always calls the real push**; it never suppresses a frame.
- All stock input is suppressed at the EW platform layer while the app is open:
  detours on `EwBspKeyEventProcess` and `EwBspTouchEventProcess` (plus the
  `EwBspGet*` getters as backup) return "no event", so the stock menu and the
  top status bar cannot open. Kernel `EVIOCGRAB` is denied (`EACCES`) on this
  device.
- The app reads raw `/dev/input/event0` (buttons) and `event1` (touch) itself.
- Buttons are **UP/DOWN**, not OK/BACK: evdev 28 → EW UP, evdev 158 → EW DOWN.
  Short press moves; hold DOWN (≥700 ms) selects; hold UP (≥700 ms) exits.
- Painting freezes while `/data/local/tmp/n3_capture` exists, so screenshots are
  always complete frames.
- The window area is backed up and restored on exit.

## API (`n3app.h`)

```c
typedef struct { unsigned int *pixels; int w, h, stride; } n3_surface;

void n3_fill(n3_surface*, int x, int y, int w, int h, n3_color);
void n3_frame_rect(n3_surface*, int x, int y, int w, int h, int t, n3_color);
int  n3_text_width(const char *text, int scale);
void n3_text(n3_surface*, int x, int y, const char *text, int scale, n3_color);

typedef struct n3_app {
    const char *name;
    int x, y, w, h;                 /* window rect; 0 => default centred */
    void (*on_open)(n3_surface*);
    void (*on_tick)(n3_surface*, unsigned int frame);
    void (*on_key)(int key);
    void (*on_close)(void);
} n3_app;

int n3_start(const n3_app*, void *(*loader_dlsym)(void*, const char*));
```

Colors are `0xAARRGGBB` (stored little-endian as BGRA, matching the N3).
`on_key` receives `N3_KEY_BACK` / `N3_KEY_ENTER`; BACK also closes the window.

## PC → goggles display tunnel

[`examples/hardware_tunnel/`](examples/hardware_tunnel/) documents the proven
1080p60 path: `vc8000d` hardware decoder tunnelled into `extra_blending`, with
the exact ports, buffer ownership, codec-config feed, host sender settings and
failure modes. `n3_hw_tunnel.h` has the constants/helpers. Reference
implementation: `../mods/h264/h264live.c`.

## Build

```
powershell -ExecutionPolicy Bypass -File build.ps1
# or a custom app:
powershell -ExecutionPolicy Bypass -File build.ps1 -Src ..\myapp\mod.c -Out ..\myapp\myapp.so
```

Output goes to `dist/` by default. The build is aarch64, freestanding, and has
no undefined imports (`zig cc -nostdlib`).

## Install and run

1. Push to `/vendor/<app>.so` (needs the root shell + `/vendor` remount).
2. Add it to the mod list the UI is started with, e.g.
   `n3ctl.start_ui(mods=["/vendor/n3hello.so", "/vendor/hook_capture.so"])`.
3. `touch /data/local/tmp/n3_app_on` to show it; `rm` the file to hide it.
4. BACK also hides it.

The included `tools/test_sdk.py` does deploy → show → capture → hide → capture
and writes PNGs under `SDR findings/debug/sdk-test/`.

## Template

`template/mod.c` shows text, a progress bar, a frame counter, and key logging.
Copy it to start a new app. `template/mod.json` is the manifest.

## Limits

- One window, default 800×340 (max 1000×600); full-screen apps are not done yet.
- Text is ASCII in a built-in 5×7 font (A–Z, 0–9, space, `-=.:/`).
- App code runs on its own thread; **never call EW/DJI UI APIs from it**.
- A crash in the app still takes down `dji_glasses`; use the `watch` command to
  auto-recover during development.
- Stock key/touch are suppressed via `EwBspKeyEventProcess` /
  `EwBspTouchEventProcess`. The app's own raw **touch** swipe/tap handling is
  implemented but not yet verified on the touchpad; buttons are the reliable
  input for now.
- For live UI debugging, use `tools/debug_live.py` (160×90, ~57 fps).

## Mod contract (learned the hard way, 2026-11-26)

A mod loaded by `n3mods.so` must follow this or the loader rejects it:

1. **Export `natartos_mod_init`:**
   ```c
   int natartos_mod_init(void *(*loader_dlsym)(void *, const char *));
   ```
   The loader passes its own `dlsym`; store it and use it for everything
   (`dlopen`, `dlsym`, `pthread_create`, …).
2. **Never reference `dlopen`/`dlsym` directly.** A direct reference fails at
   load with `cannot locate symbol "dlopen" referenced by "<mod>.so"`.
3. **Install mode 755** in `/vendor`. A 644 `.so` is not loaded.
4. **Write `/vendor` through the `dji_services` push path** (the app's
   `n3ctl.push_file`). The `su` adb shell can remount `/vendor` rw but cannot
   write `vendor_file` itself.
5. **Do not block the loader.** `natartos_mod_init` runs at UI start: hand work
   to a thread.
6. **`capture` and `overlay` are mutually exclusive** — they graft the same
   symbols, and loading both double-hooks `push_frame`. The app replaces one
   with the other automatically.

## Available components

Vendor OMX is reachable from inside `dji_glasses`:
`dlopen("libOmxCore.so")` then `OMX_Init` / `OMX_GetHandle`. The core must be
addressed with **OMX version 1.0.0** (`nVersion` 1.0.0); 1.1.2 returns
`OMX_ErrorVersionMismatch` on every call. See `mods/h264/` for a worked example
and `mods/h264/include/` for the Khronos headers.

## Safety

- No `/system` writes, no dm-verity, no OTP/RPMB, no bootloader.
- Only a backup/restore of the window rectangle in the live dmabuf.
- No frame suppression; stock OSD, battery and theme stay visible.
- Hiding the app restores the exact pixels that were under the window.
