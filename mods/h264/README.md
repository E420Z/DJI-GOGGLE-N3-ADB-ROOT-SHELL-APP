# mods/h264 — PC stream, Stage 2 (hardware H.264)

Goal: PC sends H.264, the goggles decodes it with the **hardware** decoder and
puts it on the display, so 1080p60 fits in ~1 MB/s.

## Status

| Step | State |
|---|---|
| PC encode (NVENC) | **done** — 1080p60 at 8× realtime, 8 Mbps (RTX 4070 SUPER, h264_nvenc p1/ll) |
| B1: OMX core + component enumeration inside `dji_glasses` | **works** — 57 components, 5 decoders, 3 encoders |
| B2: open `vc8000d`, decode a canned stream into the framebuffer | not started |
| B3: live TCP receive | not started |

### B1 evidence (2026-11-26)

`natartos.log`:

```
[h264] probe: libOmxCore opened
[h264] probe: OMX_Init err=0
[h264] OMX.dji.video_decoder.avc.ffmpeg
...
[h264] probe: components=57
[h264] probe: decoders=5
[h264] probe: encoders=3
```

## Mod contract (learned the hard way)

A mod loaded by `n3mods.so` must:

1. export `int natartos_mod_init(void *(*loader_dlsym)(void *, const char *))`
2. use that pointer for everything (`dlopen`, `dlsym`, `pthread_create`, ...).
   A direct reference to `dlopen` makes the load fail with
   `cannot locate symbol "dlopen"`.
3. be installed with mode **755** in `/vendor`.

`/vendor` must be remounted rw by the `su` adb shell, but the file itself must be
written through the `dji_services` push path — `su` cannot write `vendor_file`.

## Build / deploy

```powershell
sdk\build.ps1 -Src ..\mods\h264\probe.c -Out ..\mods\h264\n3h264.so
```

Push to `/vendor/n3h264.so`, chmod 755, add it to `/data/local/tmp/n3mods.list`
(colon or newline separated — the loader converts both), restart the UI.
