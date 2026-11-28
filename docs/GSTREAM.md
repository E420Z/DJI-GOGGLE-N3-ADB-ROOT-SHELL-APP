# Goggles Stream — 1080p60 video out to the PC

The goggles' **own hardware encoder** (vc8000e) is read live and sent to this PC
over the USB link, with no re-encode. This is the goggles → PC direction; the
PC → Goggles page is the opposite.

Measured on the owner's N3 (firmware 0900), 2026-11-27.

## What you get

| | |
|---|---|
| Resolution | 1920×1080 |
| Frame rate | **59–60 fps** |
| Bitrate | ~2.0–2.2 Mbps on a static UI; **10 Mbps cap** in motion |
| Codec | H.264 High, level 5.2 (vc8000e) |
| Transport | TCP 5571 over RNDIS (`192.168.60.2`) |
| PC playback | ffmpeg remux to fragmented MP4 → loopback HTTP 8771 → MSE |
| Re-encode | **none** — the bitstream is copied |

The stream starts with the real sequence header taken from the vendor encoder
(`00 00 00 01 67 64 00 34 … 00 00 00 01 68 ee 3c b0`, 40 bytes), so decoders
can start immediately even though the MDC channel itself carries only slices.

## Architecture

```
goggles                                                        PC
──────────────────────────────────────────────────────────────────────────────
OMX.dji.video_reader.avc.mdc                                   app/gstream.py
  channel zv900_app_liveview_chn   ── H.264 ── TCP 5571 ──►  socket reader
  (already fed by media_server)                                │
        ▲                                                      ▼
        │                                              ffmpeg -c copy
  n3videoout.so (preload in dji_glasses)                frag_keyframe MP4
  prepends SPS/PPS, 4 MB drop-to-newest ring                   │
                                                               ▼
                                                    127.0.0.1:8771/stream.mp4
                                                               │
                                                      WebView2 page (MSE)
```

- The mod is a **read-only consumer** of the channel. It never starts or stops
  the media pipeline.
- The page is `app/web/goggles-stream.*`; the backend is `app/gstream.py`.
- Writes are limited to `/vendor/n3videoout.so` and `/data/local/tmp`
  (`videoout_on`, `videoout.stat`). **Nothing in `/system` is touched.**

## Using it

1. Connect the goggles over USB and start the root shell (Connection page).
2. Install **ffmpeg** on the PC (see Requirements).
3. Open **Goggles Stream** → **Start stream**.
4. The first start may restart the goggles UI to load the mod (~25 s); later
   starts are much faster.
5. **Stop stream** removes the marker, turns the vendor liveview properties off
   and stops ffmpeg. The page can go fullscreen (button, double-click or `F`).

The status file `/data/local/tmp/videoout.stat` reports what the mod did:
`client`, `frames`, `bytes`, `dropped`, `sent`.

## Measured

```
captured 1 681 871 bytes in 6.01 s = 2237 kbps
nal: slice 349, IDR 7, SPS 1, PPS 1, AUD 355
fps (AUD): 58.87
```

A 4-second pull from the local HTTP endpoint decoded with **0 errors**; the
extracted frame was the real goggles UI at 1920×1080.

The channel's own stats confirm the encoder: `avg_fps 60.01`, `avg_interval
16.66 ms`.

## Latency

The first build fragmented the MP4 only at keyframes (`frag_keyframe`), so the
muxer could hold a whole GOP (~0.8 s) before the browser saw anything. The
current pipeline:

- **`-movflags +frag_every_frame`** — one `moof`/`mdat` per frame (~16.7 ms),
  plus `-flush_packets 1`.
- **512 KB ring** (was 4 MB) and `flush()` after every segment.
- **`TCP_NODELAY`** on both the goggles socket and the PC socket.
- MSE keeps **0.12 s** behind the live edge and jumps when it falls more than
  **0.6 s** behind (was 0.4 s / 2 s).

Offline validation against a captured 1080p60 stream: **312 frames → 312
fragments**, `ffprobe` 1920×1080 at ~60 fps, **0 decode errors**.

The page shows the player buffer (`gsPlayer`). End-to-end glass-to-glass still
needs a device run; `app/state/gstream_latency_test.py` samples the real
WebView2 player.

## Why the bitrate stops at 10 Mbps

`/system/etc/app_liveview_pipe.json` builds the graph:

```
LCDC writeback → OMX.dji.video_reader.mdc → vc8000e encoder (bitRate 10000000)
              → OMX.dji.iv_renderer.avc.mdc_sender → zv900_app_liveview_chn
```

`bitRate` is a literal in a **read-only `/system` file**. This project never
writes `/system` (dm-verity mode 2, no unbrick), so the existing pipe cannot be
raised above 10 Mbps.

### The 60 Mbps path (tested pieces)

- The raw LCDC YUV channel (`zv900_liveview_lcdc_chn`) can be read at
  **59.3 fps**, real 1920×1080 frames, while the normal pipe runs.
- A second vc8000e instance is available and **accepts 60 Mbps** (the vendor
  encoder test reports a 40-byte sequence header).
- A 60 Mbps mode therefore needs our own reader → encoder graph inside
  `dji_glasses` (copying or sharing the YUV buffers), not a `/system` edit.
  It is a separate, heavier mod and is not part of this page yet.

Until then the page reports the honest ceiling: 1080p60, ~10 Mbps max.

### 60 Mbps tunnel progress (2026-11-28)

`mods/h264/enctunnel.c` opens a second `vc8000e`, subscribes the LCMD reader to
`zv900_liveview_lcdc_chn`, and **tunnels** the reader output straight into the
encoder (`OMX_SetupTunnel(reader, out, encoder, 0)`). Tunnelling is required:
manual YUV copies crash `VC8000EVideoEnc::processBuffer`.

Measured:

- Stable 1920×1080 encode, ~357 output buffers in 3 s (~119 fps on the 120 Hz
  LCDC writeback), clean Idle/free/handle teardown, no crash.
- Output port 1 `nBitrate=60000000` set at Loaded is **read back as 60000000
  after Idle**, so the 60 Mbps target is in the port definition.
- The standard runtime bitrate config (`OMX_IndexParamVideoBitrate` through
  `OMX_SetConfig`, CBR) reaches `duss_hal_venc_set_ratectrl` but the vendor
  call returns `0x80001001` for every value; the port definition is the working
  path (the vendor `PipeBuilder` sets the same field with
  `OMX_SetParameter(0x02000001)`).
- Encoder mode (`0x7f000026`, storage=0 / liveview=1) is applied.
- On static UI content the stream is 7–11 Mbps at a 60 Mbps target (VBR) and
  7.5 Mbps at a 10 Mbps target — the target is honored, but the menu simply
  does not need the bits. **The real 60 Mbps number needs a live drone feed**
  on the goggles (O4 connected), where the LCDC content has full detail.
- The writeback carries the UI/composited plane. The PC‑video
  `extra_blending` plane is not in it while the UI lives; the fork child that
  hides the UI stops the app-liveview pipe, so it cannot be used to synthesise
  motion for this test.
- The encoder does not emit in-band SPS/PPS; prepend the vendor 40-byte header
  (`videoout.c`) before decoding or streaming.
- **Bitrate proof (transcode):** `mods/h264/enctranscode.c` tunnels the
  `vc8000d` decoder into the same encoder and feeds 1080p60 NVENC noise. It
  produced **26.9 MB in 3 s (~71 Mbps)** at the 60 Mbps target, then crashed in
  `VC8000EVideoEnc::processBuffer+2844` (the transcode graph is a proof only).
  The reader → encoder tunnel remains stable.
- **Frame rate:** both tunnels emit ~2 frames per input frame (~120 fps of
  60 Hz content, duplicates). `OMX_IndexConfigVideoFramerate` and the AVC intra
  period return `0x80001006`, so the encoder does not drop. A 60 Mbps raw
  stream therefore needs `-framerate 120` on the PC (or a future frame-drop
  path). The prefixed vendor SPS/PPS declares 25 fps, so raw input must always
  set `-framerate` explicitly.


## Requirements

- Root shell (the mod is preloaded into `dji_glasses`).
- **ffmpeg** on the PC, in `PATH`, in `tools\ffmpeg.exe`, or via
  `FFMPEG=C:\path\to\ffmpeg.exe`. Without it the page explains what is missing
  and will not start a session.
- The mod source is `mods/h264/videoout.c`; build it with
  `sdk/build.ps1 -Src ..\mods\h264\videoout.c -Out ..\mods\h264\n3videoout.so`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| “No listener on 5571” | The mod is not in the UI. Press Start again (it restarts the UI), or check `grep n3videoout /proc/$(pidof dji_glasses_patched)/maps`. |
| “ffmpeg was not found” | Install ffmpeg or set `FFMPEG`. |
| Black video for <1 s | The stream starts mid-GOP; the next IDR arrives within ~0.8 s. |
| Video freezes, stats stop | The USB link dropped; press Stop then Start. Props are reset on stop. |
| Props left at 1 | The app crashed mid-session. Run `setprop test.applv.func.on 0; setprop test.applv.enable 0` from Root Shell, or reboot. |
| UI looks wrong after a start | **Recover stock UI** on Connection; nothing is installed in the boot chain. |

## Safety

- Read-only tap of a channel `media_server` already writes; the mod does not
  start, stop or reconfigure the pipeline.
- `/vendor` is remounted read-write only for the push, then read-only again.
- `Stop stream` always removes the marker and clears the vendor properties.
- If the screen goes black, use **Recover stock UI** or power-cycle the goggles.
- No `/system`, verity, partition, OTP or radio writes.
