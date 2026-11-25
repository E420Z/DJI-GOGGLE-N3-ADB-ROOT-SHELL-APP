# Live USB debug stream on the N3

Date: 2026-11-25. Owner's device. Read-only capture; no display hook, no frame
suppression.

## Why

Screenshots are too slow to see flicker/tearing. This streams the live UI over
USB in real time so changes can be watched and recorded.

## How it works

`/vendor/n3live.so` is a preload mod in `dji_glasses`:

- Finds the two live 1920×1080 `/dmabuf:` surfaces in `/proc/self/maps`.
- Downscales by 12 → **160×90 BGRA**.
- Writes `'N3LV' + u16 w + u16 h + u32 seq` + pixels to
  `/data/local/tmp/n3live.fifo` with **non-blocking** writes.
- If no reader is connected, writes are dropped; it never blocks the UI.

Host: `tools/debug_live.py` creates the FIFO, runs `adb exec-out cat`, parses
frames, shows them with Tkinter, and can record an APNG.

## Measured

| Resolution | FPS | Notes |
|---|---:|---|
| 160×90 (scale 12) | **~57 fps** | real-time; best for flicker |
| 240×135 (scale 8) | ~19 fps | bandwidth-limited |

The limit is ADB/FIFO throughput (~2.5–3.3 MB/s), not CPU or a missing codec.

## Toolya comparison (from toolya.dev, 2026-11-25)

- **Screen → live monitor**: Toolya's own page says **~2–3 fps**, because each
  frame is a full 8 MB capture over ADB.
- **PC Stream**: PC → goggles, JPEG over ADB, 720p/30 fps, injected via
  `fb_shared`. That is the opposite direction.
- **60 fps H.264**: the goggles' camera/live-view feed (legacy `RMVT`, or the
  modern `0x574a` channel). It is DJI-encoded and is **not** a guaranteed
  pixel-perfect UI mirror; menus/OSD may be absent.

So there is no Toolya UI codec to copy. Our 160×90/57 fps stream is already
faster than Toolya's UI mirror for debugging.

## Usage

```
# stock UI or an already-loaded app
py -3.12 "SDR findings/tools/debug_live.py" --seconds 10 --record stock.apng

# deploy and show the menu app while streaming
py -3.12 "SDR findings/tools/debug_live.py" \
  --app "SDR findings/n3sdk/dist/n3menu.so" --show --seconds 15 --record menu.apng

# no window, just record
py -3.12 "...\debug_live.py" --no-window --seconds 8 --record out.apng
```

Press Ctrl+C to stop; the tool restores stock USB.

## Higher resolution later

For 320×180+ at 60 fps, send only changed blocks (delta/RLE) between frames.
The UI is mostly static, so this fits well and avoids any hardware encoder.
Hardware H.264 of the UI is possible but needs MediaCodec/Surface and
BGRA→YUV work; it is overkill for flicker diagnosis.
