# mods/h264 — PC stream, Stage 2 (hardware H.264)

Goal: PC sends H.264, the goggles decodes it with the hardware/ffmpeg decoder
and puts it on the display, so 1080p60 fits in ~1 MB/s.

## Goggles → PC video out (2026-11-27)
The other direction is now shipped: `videoout.c` / `n3videoout.so` reads the
encoded channel with `OMX.dji.video_reader.avc.mdc`, prepends the **real**
vc8000e SPS/PPS and serves Annex-B H.264 on **TCP 5571**.

- Armed by `/data/local/tmp/videoout_on`; stops when the file is removed.
- 4 MB drop-to-newest ring; one client at a time; sender thread never blocks
  the OMX callback.
- Stats: `/data/local/tmp/videoout.stat` (`client`, `frames`, `bytes`,
  `dropped`, `sent`).
- Measured **59–60 fps at 1920×1080**; 10 Mbps is the vendor pipe's cap.
- Build: `sdk\build.ps1 -Src ..\mods\h264\videoout.c -Out ..\mods\h264\n3videoout.so`
- The PC side is `app/gstream.py` + the **Goggles Stream** page. See
  [`docs/GSTREAM.md`](../../docs/GSTREAM.md).

`yuvprobe.c` is the read-only probe for the **60 Mbps** route: it reads the raw
1080p YUV channel (`zv900_liveview_lcdc_chn`) at 59.3 fps. A second vc8000e
instance accepts 60 Mbps, so a custom reader→encoder graph is the only way past
the 10 Mbps pipe cap (which lives in read-only `/system`).

## 60 Mbps encoder probe (experimental, not shipped)

`encprobe.c` / `n3encprobe.so` opens a **second vc8000e** at 60 Mbps, copies the
LCDC YUV frames into it, and writes the elementary stream to
`/data/local/tmp/enc_hi.h264`.

- Armed by `/data/local/tmp/enc_on`; one shot.
- `/data/local/tmp/enc_synth` replaces the UI frames with a moving pattern, to
  measure the encoder's true bitrate ceiling (the UI is mostly static).
- 3 s / 24 MB cap, then Idle → free buffers → `OMX_FreeHandle` (resolved by
  `dlsym`; this core does not export it in the global namespace).
- Writes only `/data/local/tmp`; the display pipeline is untouched.

Manual run:

```sh
touch /data/local/tmp/enc_synth          # optional: synthetic motion
touch /data/local/tmp/enc_on
sleep 4
# pull /data/local/tmp/enc_hi.h264
```

The next step is a TCP 5572 variant so the page can play the 60 Mbps stream
directly, with the encoder's own CSD (SPS/PPS) as the sequence header.

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

## PC -> goggles decoder probe (experimental)

`videc.c` / `n3videc.so` answers whether the vendor H.264 decoder can be used as
a live display source:

- feeds `/data/local/tmp/vdec_in.h264` as **one real access unit per buffer**
  with `OMX_BUFFERFLAG_ENDOFFRAME` (no zero padding, no immediate EOS);
- tests `OMX.dji.video_decoder.avc.ffmpeg` by default, or
  `OMX.dji.video_decoder.avc.vc8000d` when `/data/local/tmp/vdec_vc` exists;
- logs `pre_eos frames` (the key number), `empty calls`, `eos`, and writes the
  first 8 NV12 frames to `/data/local/tmp/vdec_out.nv12`;
- armed by `/data/local/tmp/vdec_on`, one shot, full buffer/FreeHandle teardown.

A non-zero `pre_eos frames` means the decoder is usable for a live path. The
remaining piece is NV12 -> BGRA for `fb_shared` (libyuv/NEON) or a YUV overlay.
