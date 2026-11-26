# mods/stream — PC screen into the goggles

Working configuration, verified on the owner's N3 (2026-11-26).

## Architecture

```
PC (PIL ImageGrab -> JPEG)  --TCP 5570-->  fb_receiver  (runs as su)
    -> /data/local/tmp/fb_shared (64-byte header, counter at 0, 2 x 8,294,400 B BGRA)
    -> hook_overlay.so inject thread / push detour -> display
```

## Frame format

```
[u32le jpeg_len][jpeg bytes]   repeated
```

The receiver scales/letterboxes any size to 1920x1080 and converts RGB -> BGRA.

## Latency

The goggles decodes one 1080p frame in ~122 ms plus ~80 ms to publish it, so
1080p tops out near 5 fps. Sending faster than that only builds a queue.

Two things keep latency low:

- `fb_receiver` **drops stale frames**: when several frames are already queued it
  skips to the newest before decoding, and it sets `SO_RCVBUF` to 256 KB so a
  backlog cannot grow into seconds.
- `pcstream.py` **paces** to the rate the goggles can actually consume.

Practical settings:

| Size | Device per frame | Sender setting |
|---|---|---|
| 1280×720 | ~45 ms | `--fps 12` (comfortable) |
| 960×540 | ~25 ms | `--fps 15` |
| 1920×1080 | ~200 ms | `--fps 5` |

## Anti burn-in (DuScreenSaver)

The goggles runs an OLED screen saver: a bitmap slideshow that steps every
~1.6 s. It is dismissed by **key input**, not by motion. While `fb_hold` exists
the hook sends a BACK key every ~20 s, which keeps it off the screen; the PC
frame covers the UI, so the key is invisible.

## Run

```powershell
# on the goggles (su/adb), file must be labelled system_data_file:
adb push mods/stream/fb_receiver /data/local/tmp/fb_receiver_new
adb shell su 0 chcon u:object_r:system_data_file:s0 /data/local/tmp/fb_receiver_new
adb shell su 0 chmod 755 /data/local/tmp/fb_receiver_new
adb shell 'cd /data/local/tmp && setsid ./fb_receiver_new >/dev/null 2>&1 &'

# on the PC
py -3.12 app/tools/pcstream.py --size 1280x720 --fps 12
```

Stop with `pkill -TERM fb_receiver_new`: it removes `fb_override`/`fb_hold`,
touches `fb_stop` so the hook stops injecting, and the live UI repaints.

## Gotchas (all cost time)

- Binary must run in `u:r:su:s0` (root ADB); `dji_services` cannot exec `/data`.
- File label must be `system_data_file`; `shell_data_file` is unreadable to `su`.
- A stale `/data/local/tmp/fb_stop` silently disables injection; the receiver
  clears it at startup.
- The hook's cleanup used to delete `fb_shared` and kill the receiver, which
  broke every restart. It no longer does.
