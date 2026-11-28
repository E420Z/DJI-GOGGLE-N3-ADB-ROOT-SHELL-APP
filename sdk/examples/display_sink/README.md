# Display sink (`extra_blending`) — SDK example

This is the working PC → goggles display path:

```
decoded NV12 frames
  -> OMX.dji.iv_renderer.yuv.extra_blending
  -> lcdc video plane 4
  -> panel
```

The reference implementation is
[`../../mods/h264/rendprobe.c`](../../mods/h264/rendprobe.c). Build it with the
normal SDK builder:

```powershell
cd sdk
powershell -ExecutionPolicy Bypass -File build.ps1 `
  -Src "..\mods\h264\rendprobe.c" -Out "..\mods\h264\n3rendprobe.so"
```

## Required sink config

Ports:

| Port | Size | Format | Buffers |
|---|---|---|---|
| 0 main | 1920×1080 | YUV420SP | 7 |
| 1 sub | 640×360 | YUV420SP | 7 |

URL (passed via `OMX_SetParameter(component, 0x0100000D, &buf)`):

```json
{"config_file":"/etc/display_frame_rate_map.json",
 "enable_aux_liveview":false,
 "sub_stream_h_offset":144,"sub_stream_v_offset":64,
 "sub_stream_width":496,"sub_stream_height":280,
 "notify_sub_stream_alive_status":true}
```

Struct:

```c
u32 nSize   = strlen(url) + 0x0d;
u32 nVersion = 1;
char url[];   // at offset 8, NUL-terminated
```

The `config_file` maps the input fps (60) to
`DUSS_DISP_RES_1920X1080_60_0000HZ`.

## What the probe learned

- The sink accepts the URL and frames (`sent=1200 empty=1199`).
- dmesg shows video plane 4 at `alpha 255, order 0`, displayed at 60 Hz.
- The UI gfx0 plane 5 is `order 2` and covers the video plane.
- Backlight `aw99703-bl` is at max; not the problem.
- Fork mode: a child forked from the UI inherits the display/gfx fds. Closing
  fds 3..1023 and killing the UI parent releases gfx0; the video plane stays.

## Not yet a frozen API

A full `n3_display_sink_open/push/close` SDK API is best frozen **after** the
video plane is visibly confirmed without the UI gfx layer. The probe is the
reference for now.
