# mods/h264 — PC stream, Stage 2 (hardware H.264)

Goal: PC sends H.264, the goggles decodes it with the hardware/ffmpeg decoder
and puts it on the display, so 1080p60 fits in ~1 MB/s.

## Status

| Step | State |
|---|---|
| PC encode (NVENC) | **done** — 1080p60 at 8× realtime, 8 Mbps (RTX 4070 SUPER, h264_nvenc p1/ll) |
| B1: OMX core + component enumeration inside `dji_glasses` | **works** — 57 components, 5 decoders, 3 encoders |
| B2a: decode a canned file to NV12 | **works** via `OMX.dji.video_decoder.avc.ffmpeg` |
| B2b: write frames into the display path | not started |
| B3: live TCP receive | not started |

## B2a findings (2026-11-26)

Decoder opened and configured:

| Port | Direction | Format | Buffers |
|---|---|---|---|
| 0 | input | AVC, 1920×1080 | 3 × 262,144 B |
| 1 | output | NV12 (`OMX_COLOR_FormatYUV420SemiPlanar`), 1920×1080 | 4 × 3,110,400 B |

Measured: fed 3 × 256 KB chunks → **3 frames decoded, 9,331,200 bytes**
(= 3 × 3,110,400, exactly NV12 1080p) with EOS set.

Three things cost time and are worth remembering:

1. **The component wants OMX version 1.0.0.** Passing 1.1.2 returns
   `0x8000100F` (OMX_ErrorVersionMismatch) on every parameter call.
2. **`vc8000d` is not drivable this way.** It accepts configuration, reaches
   Executing, and accepts buffers (`EmptyThisBuffer`/`FillThisBuffer` return 0),
   but never invokes a callback — it needs vendor-specific setup we do not have.
3. **`OMX.dji.video_decoder.avc.ffmpeg` decodes.** It consumes roughly one
   picture per buffer.

## Open item

One access unit per buffer stalls the ffmpeg component (no callbacks), while
full 256 KB buffers work but only decode one picture each. Next: find the
buffer/flag convention it expects, or feed AUs padded to the advertised buffer
size and confirm it walks the whole buffer.

## Mod contract (learned the hard way)

A mod loaded by `n3mods.so` must:

1. export `int natartos_mod_init(void *(*loader_dlsym)(void *, const char *))`
2. use that pointer for everything (`dlopen`, `dlsym`, `pthread_create`, …).
   A direct reference to `dlopen` makes the load fail with
   `cannot locate symbol "dlopen"`.
3. be installed with mode **755** in `/vendor`.

`/vendor` must be remounted rw by the `su` adb shell, but the file itself must be
written through the `dji_services` push path — `su` cannot write `vendor_file`.

## Build / deploy

```powershell
sdk\build.ps1 -Src ..\mods\h264\decode.c -Out ..\mods\h264\n3h264.so
```

Push to `/vendor/n3h264.so`, chmod 755, add it to `/data/local/tmp/n3mods.list`,
restart the UI. The decoder runs on a worker thread so UI init is never blocked.
