# Live USB debug stream on the N3

Date: 2026-11-25. Owner's device. Read-only capture; no display hook, no frame
suppression.

## Why

Screenshots are too slow to see flicker/tearing. This streams the live UI over
USB in real time so changes can be watched and recorded.

## How it works

`/vendor/n3live.so` is a preload mod in `dji_glasses`:

- Finds the two live 1920×1080 `/dmabuf:` surfaces in `/proc/self/maps`.
- Downscales by an integer factor selected at runtime from
  `/data/local/tmp/n3live.cfg` (`scale=12` … `scale=1`).
- Writes `'N3LV' + u16 w + u16 h + u32 seq` + pixels to
  `/data/local/tmp/n3live.fifo`.
- Non-blocking, chunked writes with a 1 MB pipe. If a frame cannot complete
  (reader stalled / partial write), it closes the FIFO; the host reopens it and
  resyncs on the next header. It never blocks the UI thread.

Host: `app/ui/live.py` (and `tools/debug_live.py`) creates the FIFO, runs
`adb exec-out cat`, parses frames, and displays/records them.

## Measured (2026-11-26)

| Resolution | Scale | FPS | Notes |
|---|---:|---:|---|
| 160×90 | 12 | **~58** | real-time; best for flicker |
| 240×135 | 8 | ~30 | |
| 320×180 | 6 | ~17 | |
| 480×270 | 4 | ~12 | |
| 640×360 | 3 | **~8** | verified |
| 960×540 | 2 | ~3 | |
| 1920×1080 | 1 | **~0.9** | verified; ~8.3 MB/frame |

FPS is limited by USB/ADB throughput; higher resolution lowers it. The app's
resolution selector changes the scale live (the mod re-reads the cfg within
~2 s).

## Freeze fix (2026-11-26)

The old stream could freeze after ~10 s. Two causes:

1. The mod wrote a 57 KB frame with one non-blocking `write`; a partial write
   left the stream misaligned.
2. The host reader treated a bad header as `continue` and never resynced; it
   also blocked forever if `adb exec-out` died.

Fixes:

- Mod: chunked writes, 1 MB pipe, and close the FIFO on any incomplete frame.
- Host: a background pump thread + queue (Windows-safe; `select()` does not
  work on Windows pipes), exact reads with timeouts, and automatic
  `adb exec-out` restart + resync on EOF/bad header.

Verified: 60 s run at 160×90 → 640×360 → 1920×1080, **0 reader restarts**.

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

## In the app

The app's **E42OZ → Start live** path uses this same stream through
`app/ui/live.py`. The live panel has a resolution selector (160×90 …
1920×1080). Changing it writes `n3live.cfg`; the mod applies it within ~2 s.
Verified on 2026-11-26: 160×90 ~58 fps, 640×360 ~8 fps, 1920×1080 ~0.9 fps,
with **0 reader restarts** over 60 s.

## Usage (standalone debug tool)

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

## Notes

Raw BGRA is bandwidth-bound: 1080p is ~8.3 MB/frame, so ~0.9 fps over ADB.
For higher framerate at high resolution later, send only changed blocks
(delta/RLE) or use a hardware encoder; both are unnecessary for flicker
diagnosis today.
