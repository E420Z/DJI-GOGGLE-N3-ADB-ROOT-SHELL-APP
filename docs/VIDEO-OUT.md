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
