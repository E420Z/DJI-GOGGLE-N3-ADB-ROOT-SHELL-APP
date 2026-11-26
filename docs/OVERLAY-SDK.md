# N3 on-screen overlay — working

Date: 2026-11-25. Owner's device. This supersedes the failed natartos overlay
test in `DISPLAY-OVERLAY-N3.md`.

## Result

A safe on-screen window now works on the N3. Two independent proofs:

1. `paint-mod/` — a minimal paint test: a panel with title, text, animation,
   and a frame counter drawn over the stock UI, then fully restored.
2. `n3sdk/` — the same approach packaged as a reusable app SDK; the `HELLO`
   template renders and exits cleanly.

Screenshots:
- `debug/paint-test/paint_on_0.png` (panel visible, OSD intact)
- `debug/paint-test/paint_off_0.png` (area restored)
- `debug/sdk-test/sdk_on_0.png` (SDK window, `FRAME 37`)
- `debug/sdk-test/sdk_off_0.png` (restored)

## How it avoids the old black screen

The natartos overlay scanned for G3 dma-bufs, injected its own frame, and
**suppressed the real push** when injection was active. On the N3 that left a
black screen.

This design does the opposite:

- It never suppresses a frame; the detour always calls the real push.
- It finds the two real `8,294,400`-byte `/dmabuf:` surfaces in
  `/proc/self/maps` and composites a **window** into them.
- The app draws into a **double-buffered offscreen canvas**. The published
  canvas is blitted inside a `duss_hal_display_push_frame` detour, **right
  before the real push**, so the compositor cannot overwrite the window
  between frames. A fallback blit from the app thread covers static screens.
- It backs up the window rectangle before the first paint and restores it when
  the flag is removed or BACK is pressed.
- Stock OSD, battery, theme and background stay visible throughout.

## Input

Kernel `EVIOCGRAB` is denied on this device (`EACCES`), so grabbing
`/dev/input/event0/1` is not possible. Input is suppressed at the UI's BSP layer
instead:

- detours on `EwBspKeyEventProcess` and `EwBspTouchEventProcess` (defined in
  `libew_gls.so`) return without forwarding while the app is open, so no stock
  menu, top status bar, or touch gesture can react;
- `EwBspGetKeyCommand` / `EwBspGetTouchEvent` are also hooked (return 0) as
  defence in depth;
- the app reads raw `/dev/input/event0` and `event1` itself.

### Raw control mapping (measured 2026-11-26)

The N3 has a **5-way switch**, a **Back** button, and a **power button**. The
power button is **not** exposed as an input event (PMIC/OMC), so it cannot be
used by the SDK.

| Control | evdev | Code |
|---|---|---|
| 5-way up | `event3` | 103 (`KEY_UP`) |
| 5-way down | `event3` | 108 (`KEY_DOWN`) |
| 5-way left | `event3` | 105 (`KEY_LEFT`) |
| 5-way right | `event3` | 106 (`KEY_RIGHT`) |
| 5-way center | `event0` | 28 (`KEY_ENTER`) |
| Back | `event0` | 158 (`KEY_BACK`) |
| Power | — | no event |

The stock left sidebar opens on a **long center** press, so the SDK uses:

- short center → select / open page
- long 5-way **up** (held ≥ 600 ms) → open/close the overlay
- short up/down → move selection
- Back → back / close

The `EwBspGetKeyCommand` / `EwBspGetTouchEvent` getters are **not** hooked
(returning 0 crashed EW with a NULL deref); only the process hooks suppress
stock input while the overlay is open.

## Control

```
# show / hide (root shell)
touch /data/local/tmp/n3_app_on
rm /data/local/tmp/n3_app_on

# convenience
py -3.12 "SDR findings/tools/debug_ui.py" paint on
py -3.12 "SDR findings/tools/debug_ui.py" paint off
```

BACK (evdev event0, code 158) also hides the window and writes
`/data/local/tmp/n3_app_exit`.

## Screenshot-safe painting

The capture hook and the app both use dmabufs. If a screenshot is taken while
the app is mid-draw, the captured frame can contain a partial line. The SDK
freezes painting while `/data/local/tmp/n3_capture` exists, so captures are
always complete frames. This fixed a visible "sliver" artifact during testing.

## Known limits

- The push detour blits the window on the UI thread; very large windows at
  60 fps cost more memcpy. Default windows are small.
- Window only (default 800×340, max 1000×600); no full-screen mode yet.
- One app at a time; no stacking.
- Crash in the app still takes down `dji_glasses` (use `debug_ui.py watch`).
- Keys are consumed; **touch still reaches the stock UI** until a touch handler
  is hooked. Prefer buttons for now.
- The capture hook was changed to **thread-only capture (no display detour)** so
  it can coexist with the SDK's push detour.

## Safety

- No `/system`, dm-verity, partition, OTP/RPMB or bootloader changes.
- No frame suppression; the real display path is untouched.
- Hiding restores the exact pixels under the window.
- Reversible: remove the mod and restart the UI.

## Next

- Menu entry / launcher: register a mod entry and open the window from it.
- Touch mapping (`event1`) for list navigation.
- Full-screen mode with a dedicated double-buffer.
- Port the GFSK monitor to `n3sdk` for a real in-goggles app.
