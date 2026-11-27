# PC Stream — this desktop inside the goggles

Turn the goggles into a second monitor for your PC over the existing USB link.
No radio, no Wi-Fi, no capture card.

## How it works

```
PC: PIL ImageGrab -> JPEG -> TCP 5570
      |
      v
goggles: fb_receiver (su domain)          <- app/assets/fb_receiver
      -> /data/local/tmp/fb_shared (64-byte header, counter, 2 x 8,294,400 B BGRA)
      -> /vendor/hook_overlay.so          <- injects into the live dmabuf
      -> display
```

Two halves, both shipped in this repo:

| Half | File | Runs |
|---|---|---|
| Sender | `app/webapp.py` + `app/pcsender.py` (also `app/tools/pcstream.py` standalone) | PC |
| Receiver | `mods/stream/fb_receiver.c` → `app/assets/fb_receiver` | Goggles, as `su` |
| Injector | `mods/capture/mod.c` → `hook_overlay.so` | Inside `dji_glasses` |

## Requirements

1. **ADB enabled** (Connection page).
2. **Root shell started** — needed to label the receiver so `su` can execute it.
3. **Frame injection (PC stream)** mod installed from Mods & UI, then restart the
   UI. Without it the frames land in memory but nothing is displayed, so the app
   keeps Start disabled and says why.

## Using it

1. Connection → **Enable ADB** → **Start root**.
2. Mods & UI → install **Frame injection (PC stream)** → restart the UI.
3. PC Stream → choose size / fps / quality → **Start stream**.
4. **Stop** when done; the goggles returns to its normal UI.

Standalone sender:

```powershell
py -3.12 app/tools/pcstream.py --size 1280x720 --fps 12 --seconds 60
```

## Measured on the owner's N3

| Size | Goggles decode | Publish | Practical fps |
|---|---|---|---|
| 960×540 | ~25 ms | ~30 ms | ~15 |
| 1280×720 | ~57 ms | ~90 ms | **~12** (verified) |
| 1920×1080 | ~122 ms | ~80 ms | ~5 |

End-to-end at 1280×720: **10.7–11.8 fps, ~420–450 KB/s**.

## Why latency stays low

The goggles decodes in software (~57 ms at 720p), so sending faster than it can
consume would only build a queue. Two mechanisms prevent that:

- the receiver **drops stale frames** — if several frames are already queued it
  skips straight to the newest before decoding, and caps `SO_RCVBUF` at 256 KB;
- the sender **paces** to the configured fps with `TCP_NODELAY` and a small send
  buffer.

## Anti burn-in

The goggles runs an OLED screen saver (`DuScreenSaver`) that steps a bitmap
slideshow every ~1.6 s. It is dismissed by **key input**, not by motion, so while
`fb_hold` exists the hook sends a BACK key every ~20 s. The PC frame covers the
UI, so the key is invisible.

## Safety

- Writes only `/data/local/tmp/{fb_shared,fb_override,fb_hold,fb_receiver.log}`.
- The receiver binary itself lives in `/data/local/tmp`; the only `/vendor` file
  is `hook_overlay.so`, pushed through the app's remount-and-restore path.
- Never touches `/system`, dm-verity, partitions or the radio.
- Removing `fb_hold`, pressing Stop, or rebooting restores the stock UI.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Start is greyed out | ADB off, or the injection mod is not installed |
| Picture never appears | a stale `/data/local/tmp/fb_stop` — the receiver clears it at startup; reboot if in doubt |
| `Permission denied` running the receiver | wrong SELinux label; it must be `system_data_file` and run from `u:r:su:s0` |
| Seconds of lag | sending faster than the goggles decodes — lower size or fps |
| Screen saver flicker | the 20 s BACK nudge is disabled (`fb_hold` missing) |

## Why it tops out at ~12 fps (and the faster path)

The USB link is not the limit. `fb_receiver` decodes JPEG with **stb_image**
(software) and converts RGB -> BGRA with a scalar loop; at 1280x720 that is
~45 ms per frame. The device does have libjpeg-turbo
(`/system/lib64/libjpeg.so`), so a turbo/scaled decode is a possible quick win.
The better route is:

```
PC H.264 (10-20 Mbps, zerolatency, no B-frames)
  -> vendor decoder (OMX.dji.video_decoder.avc.vc8000d / .ffmpeg)
  -> NV12
  -> NV12 -> BGRA (libyuv/NEON) or a YUV overlay
  -> display
```

That removes the JPEG decode entirely and cuts USB bandwidth by ~3-5x.

Two open items:

1. **Decoder callbacks.** The earlier probe padded every access unit to the full
   buffer and never set `OMX_BUFFERFLAG_ENDOFFRAME`. `mods/h264/videc.c`
   (`n3videc.so`) feeds one real AU per buffer with `ENDOFFRAME`, no B-frames,
   and reports how many frames arrive **before EOS** - the go/no-go test for a
   live decoder.
2. **Display format.** The injection hook only accepts BGRA in `fb_shared`;
   decoded NV12 needs a NEON/libyuv conversion (~2-4 ms at 720p) or a YUV
   overlay plane.

Neither is wired into the page yet; both are bench tests.

## Lowest-latency 1080p60 path (PC half validated)

The best path is **H.264 all the way**, not JPEG:

```
dxcam (DXGI, 60 fps) -> NVENC 1080p60 (p1/ll, bf=0, CBR 20 Mbps)
  -> Annex-B over TCP (NODELAY)
  -> goggles vendor decoder (vc8000d/ffmpeg)
  -> NV12 -> BGRA (NEON) -> fb_shared -> hook_overlay
```

Measured PC side on the RTX 4070 SUPER (`app/h264send.py`, local sink):

- **60.0 fps**, **19.99 Mbps**, 270 frames in 4.5 s.
- Capture + scale + NVENC: **9.3 ms** average (16.7 ms on the first
  full-screen 2048x1536 -> 1920x1080 run).
- Stream is raw **Annex-B** (starts `00 00 00 01 67 ...`), decoded with
  **0 errors** at 1920x1080.
- `dxcam` is used because `gdigrab` only reached ~24 fps at 4K and ~47-59 fps
  for a 1080p region; DXGI holds 60 fps.

Remaining gate: the goggles decoder. `mods/h264/videc.c` tests it with real
access units + `ENDOFFRAME` and reports frames **before EOS**. If that is
non-zero, the receiver becomes: AU splitter -> decoder -> NV12 -> BGRA ->
`fb_shared`. Expected glass-to-glass ~35-50 ms, versus 100-300 ms for the
JPEG/stb path.

If the vendor decoder cannot be driven, the fallback is **libjpeg-turbo**
(the device has `/system/lib64/libjpeg.so`) with half-scale decode, which can
reach 720p60 but not 1080p60.
