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
| `stream` (PC → goggles) | **Superseded** | The JPEG/`fb_shared` route was removed. The working path is the 1080p60 `vc8000d` hardware tunnel into `extra_blending`; see `docs/PC-TO-GOGGLES.md`. |
| `doom` | Not ported | Needs an "app" mod type our loader does not have. Separate project. |
| `input`, `mute`, `audio`, `splash` | Not ported | Marked experimental/untested upstream. |

The old JPEG receiver (`fb_receiver`) has been removed. The working PC → goggles
path is the **1080p60 hardware tunnel** (`vc8000d` → `extra_blending`), documented
in `docs/PC-TO-GOGGLES.md`; it needs no JPEG, no `fb_shared` and no extra copy.

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

Use the hardware tunnel in `docs/PC-TO-GOGGLES.md` (`vc8000d` →
`extra_blending`). The old JPEG/`fb_receiver` plan is obsolete and its files were
removed.
