# Getting 1080p video out to the PC

Measured on the owner's N3, 2026-11-26. Read-only investigation.

## The headline

The goggles is **already encoding 1920×1080 H.264 at 50 fps**, continuously,
even with no phone connected. From `logcat`:

```
OMXLcdcWBSource: [Graph11] frameReturnCallback:301 [FPS] lcdc write back frame cnt 100441 timeuse 2999ms fps 60.02
OMXVC8000Enc: [Graph1] processBuffer:1399 ... encoded Count:100499,
              resolution:1920*1080, FPS: 50000 / 1000
```

So 1080p30 is not a performance question — the hardware is doing 1080p50 right
now. The only question is **where to take the encoded stream**.

## Why the current mirror is slow

`n3live.so` (E420Z live preview) sends **raw downscaled frames** over ADB.
At 1080p that is 1920×1080×3 bytes per frame ≈ 6 MB, so ~1 fps is the ceiling
over USB. Encoded H.264 at 8–12 Mbps is ~1.5 MB/s — trivial. That is the whole
difference.

## The chain (from `/system/etc/*.json`)

```
LCDC writeback 1920×1080 @60
  → OMX.dji.video_reader.lcdc          (libOmxLcdcWBSource)
  → mdc channel  zv900_liveview_lcdc_chn
  → OMX.dji.video_reader.mdc
  → OMX.dji.video_encoder.avc.vc8000e  (libOmxVC8000Enc)   → 50 fps H.264
  → mdc channel  zv900_app_liveview_chn
  → (DJI Fly app on a phone)
```

`app_liveview_pipe.json` is that exact graph, run by `dji_media_server`.

## Components that matter (all present)

| Component | Purpose |
|---|---|
| `OMX.dji.video_reader.lcdc` | Display writeback source, 1080p |
| `OMX.dji.video_reader.mdc` / `.avc.mdc` | Read an MDC channel |
| `OMX.dji.video_encoder.avc.vc8000e` | Hardware H.264 encode |
| `OMX.dji.video_encoder.hevc.vc8000e` | Hardware H.265 encode |
| `OMX.dji.file_writer.binary` | **File sink** (default `/blackbox/fileSink`) |
| `OMX.dji.container_muxer.ffmuxer` | MP4/MOV muxer |
| `OMX.dji.video_writer.uvc` | **UVC sink** — expose as a USB camera |

Test CLIs shipped: `omx_graphcfg`, `omx_comptest`, `omx_coretest`,
`omx_recordtest`, `omx_srctest`, `omx_sinktest`, `test_mux`, `test_remux`,
`test_vdec`.

## Three routes

| Route | What you get | Risk |
|---|---|---|
| **A. Tap `zv900_app_liveview_chn`** with `video_reader.avc.mdc` → `file_writer.binary` | Live 1080p H.264, no re-encode, no LCDC contention | Attaches a second reader to a channel `media_server` writes; worst case the graph refuses, best case it just works |
| **B. Record with `omx_recordtest`** | 1080p mp4 on the goggles, then pull | The shipped wrapper also does a DUML route change (`0x4c 000200`) and an I2C mux write (`i2cset 1 0x41 0x1 0x0`) — **not run blind** |
| **C. UVC sink** | The goggles appears as a 1080p webcam in Windows | Needs a USB gadget re-composition; reversible but it re-enumerates the whole link |

A and B write only to `/data/local/tmp` or `/blackbox` (a separate rw ext4
partition), never `/system`.

## Storage note

- `/data`: 488 MB total, **192 MB free**.
- `/blackbox` (`mmcblk0p21`): rw ext4, flight logs and `flight_record`.
- `/mnt/media_rw/emulated` (`mmcblk0p24`): exFAT, 10 `*.mov` from 2026-10-11,
  ~7 MB each — the goggles does write 1080p MOV files itself.

## natartos `stream` is the wrong direction

`grom-labs/natartos` `stream` casts a **PC screen into the goggles**
(`fb_receiver` → `/data/local/tmp/fb_shared` → `hook_overlay.so` inject thread).
Patching it for N3 gives you PC → goggles, not goggles → PC.

The other half — the injection thread that reads `fb_shared` (64-byte header,
2× 8,294,400-byte BGRA slots, counter at 0, `fb_override` / `fb_stop`) — is
already in this repo as `mods/capture/hook_overlay.so`. So a PC-screen cast is
~200 lines away (write our own `fb_receiver`; upstream is AGPL-3.0).

For goggles → PC, the missing piece is not a receiver at all: it is **using the
encoded stream instead of raw frames**.

## Next step

Route A, as a bounded test: 5-second graph writing to
`/data/local/tmp/n3live.h264`, killed afterwards, then pull and check the NAL
header. It may make the goggles display flicker for a second; it does not write
anything outside `/data`.

## Attempted: launching our own tap graph

Two CLIs were tried, both bounded and both writing only to `/data`:

- `dji_media_server -i <json>` → `invalid option -- i`. The usage text advertises
  `-i` but the binary rejects it (same class of bug as `test_wl_vdec -p`).
- `media-launch-1.0 <json>` → the description is read from **argv**, not stdin
  (`-c` only sets a config path). It then rejects the graph with
  `[{ ] key and val do not match: "Edges":` — `media-launch` uses a different
  "PIPELINE-DESCRIPTION" schema from the `*.json` files `dji_media_server`
  consumes, and that schema is not documented anywhere on the device.

Net result: three vendor routes, three distinct failure modes — `test_wl_vdec`
aborts on a missing `/system` config, `omx_recordtest` starts then segfaults on
mux, and the graph runners either reject their own advertised flags or an
undocumented schema.

**The remaining clean route is a small `libmdc` client** (`mdc_service_get_channel`
→ `createReceiver` on `zv900_app_liveview_chn` → write the AVC to a file/FIFO).
That is the same API `omx_recordtest` used successfully before it crashed, so it
is known to work; it just needs our own binary. `/system/lib64/libmdcclient.so`
(136 KB) is on the device.

## Why "do what the Fly app does" is not a shortcut

`/system/etc/dji_media_service.json` lists the supported outputs, and every
host-facing transport is **disabled** on this build:

```json
"app_liveview":  { "supportable": true,  "implement_in_rec_module": true },
"wifi_liveview": { "supportable": false },
"wifi_cast":     { "supportable": false },
"wifi_sink":     { "supportable": false },
"uvc_only":      { "supportable": false },
"dp_sink":       { "supportable": false },
"hdmi_dp_in":    { "supportable": false },
"default_workmode": "liveview"
```

The only path is `app_liveview`, and it runs **inside the record module** — i.e.
it is handed to the app-link layer over the DUSS bus (`@/duss/mb/0x1c07`), not
put on a standard transport.

The host-facing bulk pipes are the five `usb_bulk_raw` FunctionFS daemons
(`bulk`, `bulk1`, `bulk4`, `bulk5`, `bulk6`). Their `/proc/<pid>/io` counters
stay at **0 bytes** while the encoder runs, so the goggles does **not** push
video to a host unless the app-link protocol asks for it and a host is
negotiating.

So "the same way the Fly app does" means reimplementing that app-link handshake
over FunctionFS — a protocol reverse-engineering job, strictly bigger than the
MDC client.

## Measured: the vendor recorder (`omx_recordtest`)

Run bounded, 5 seconds, output to `/data/local/tmp/n3rec/rec.mp4`, **without**
the factory pre-conditions.

- It read commands from stdin: `i` init, `1`+url start, `2` stop+mux, `d` destroy,
  `x` exit.
- It initialised, printed **`Record start succeed`**, and attached to
  `zv900_liveview_lcdc_chn` (YUV420SP, 3,317,760 B buffers) as a receiver and to
  `zv900_app_liveview_chn` as a sender.
- On `2` (stop + mux) it **segfaulted** (`Segmentation fault (core dumped)`).
  No file was produced.
- The device was unaffected: `dji_glasses` (868) and `dji_media_server` (886)
  stayed up, no stray processes, no leftovers.

The shipped wrapper `record_test_script.sh` also runs `dji_mb_ctrl … -c 0x4c 000200`
(route video to the e3t vdec) and `i2cset -f -y 1 0x41 0x1 0x0 w` (an I2C mux
write) before recording. That is why this was **not** run: the recorder clearly
expects that factory state, and the mux write is exactly the kind of blind
hardware poke to avoid.

## PC screen into the goggles (the other direction)

The repo already has the device half. What is deployed today is the
**capture-only** hook (`/vendor/hook_capture.so`, 84,632 B — no inject symbols).
Building `mods/capture/mod.c` with `sdk/build.ps1` produces
`hook_overlay.so` (198,912 B) containing `start_inject_thread`,
`inject_thread_fn` and `g_inject_*`, i.e. the full injection path.

Protocol (already implemented in the hook):

| Piece | Detail |
|---|---|
| `/data/local/tmp/fb_shared` | 64-byte header, counter at offset 0, then two BGRA slots of 8,294,400 B (1920×1080×4) |
| `/data/local/tmp/fb_override` | must exist; a watcher thread polls it every 500 ms and starts injection |
| `/data/local/tmp/fb_stop` | stops injection and clears the overlay |

The new build is packaged as the **experimental** `overlay` plugin
(`app/plugins/overlay/`, risk medium). Installing it restarts the goggles UI;
removing `fb_override` (or creating `fb_stop`) returns to the live UI. If the
screen stays black, use *Recover stock UI* or reboot.

Still missing for a working PC stream:

1. `fb_receiver` on the goggles: read length-prefixed JPEG from a socket,
   decode to BGRA, write the next slot, bump the counter.
2. A PC sender: grab the desktop, JPEG-encode, push frames. ADB is currently
   off, so this would run over the RNDIS link (goggles at `192.168.60.2`)
   instead.

`zig` is available locally (`sdk/build.ps1` already uses it), so the receiver can
be cross-compiled without Docker.

