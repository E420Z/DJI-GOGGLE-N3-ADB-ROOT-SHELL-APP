# natartos / toolya mods on the N3

Short answer: **most of it is already here in N3-specific form, and the one
missing piece is not the part you need for S2 video.**

`grom-labs/natartos` is a per-session mod framework for **DJI Goggles 3**
(its README says "Verified devices: DJI Goggles 3"). It is AGPL-3.0 and installs
through `toolya` (CLI or toolya.dev), writing `LD_PRELOAD` mods into `/vendor`.

## What maps to what

| natartos mod | N3 status | Notes |
|---|---|---|
| `menu` (menu framework) | **Reimplemented** | `n3menuinject.so` + `n3menu.so`: private data-source vtable copy + Reload hook. Patching the shared class vtable crashes the camera toolbar. |
| `overlay` (display hook) | **Reimplemented** | `hook_overlay.so` GOT-patches `duss_hal_display_push_frame` in `libdisp_eng.so`, captures via DMA-buf and injects frames. |
| `background` | **Already shipped** | `background` mod + Settings page. |
| `stream` (PC → goggles) | **Device half exists** | `hook_overlay.so` already reads `/data/local/tmp/fb_shared` (64-byte header, 2× 8,294,400-byte BGRA slots, counter at offset 0) and honours `fb_override` / `fb_stop`. |
| `doom` | Not ported | Needs an "app" mod type our loader does not have. Separate project. |
| `input`, `mute`, `audio`, `splash` | Not ported | Marked experimental/untested upstream. |

The **only** file worth borrowing for PC streaming is `fb_receiver.c` — the
receiver that decodes length-prefixed JPEG on stdin and publishes into
`fb_shared`. That is ~200 lines. Because the upstream is AGPL-3.0, writing our
own is cleaner than copying it into this repo.

## What natartos does *not* solve

PC Stream is **PC → goggles** (casting your desktop into the headset). It does
not capture Sparrow2 video. S2 capture is a different path entirely: the
encoded H.265 that the S2 already sends over USB bulk endpoints, dumped with
the vendor decoder. See `SPARROW2.md` §10A.

So for the S2 feature, natartos is not a dependency and porting it would not
help.

## Things we deliberately do not copy

- **`toolya natartos noverity`** — disables dm-verity on `/vendor` for the
  session. We do not need it: our mods live in non-verity `/vendor` paths, and
  the whole point of this project is to stay out of that blast radius.
- **Reboot persistence** — upstream has it on the roadmap, not implemented. Our
  loader is also per-session.
- **Their root path** — we use the `dji_blackbox` RCE and a TCP root shell.

## If you still want a PC stream

It is a small, self-contained piece of work on top of what already exists:

1. Write `fb_receiver` (JPEG in on stdin → BGRA into `/data/local/tmp/fb_shared`,
   bump the counter at offset 0, touch `fb_override`).
2. Capture the Windows desktop with `mss`/`PIL.ImageGrab`, encode JPEG.
3. Pipe frames over `adb exec-out` to the receiver.
4. Stop by removing `fb_override` or creating `fb_stop`.

That is a fun feature, but it is orthogonal to the goggles' own video and is
not needed for S2 capture.
