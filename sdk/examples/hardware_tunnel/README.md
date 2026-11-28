# Hardware 1080p60 tunnel — SDK reference

This is the proven PC → goggles display path:

```
PC desktop (BGRA)
  -> NVENC H.264/H.265 (Annex-B)
  -> USB TCP 5572  [u32le len][AU]
  -> OMX.dji.video_decoder.avc.vc8000d   (hardware, 16 in buffers)
  -> OMX_SetupTunnel(decoder, 1, sink, 0)
  -> OMX.dji.iv_renderer.yuv.extra_blending
  -> lcdc video plane 4 -> panel @ 60 Hz
```

Measured: **60.0 fps**, 30 Mbps, NVENC ~7.4 ms, no copy. The software
`avc.ffmpeg` decoder is CPU-bound at ~40 fps and is only a fallback.

## Components

| Role | Component | Notes |
|---|---|---|
| Decoder | `OMX.dji.video_decoder.avc.vc8000d` | hardware; must be tunnelled |
| Decoder (HEVC) | `OMX.dji.video_decoder.hevc.vc8000d` | tested: 60.1 fps at 20 Mbps |
| Sink | `OMX.dji.iv_renderer.yuv.extra_blending` | the Air Unit liveview plane |
| Fallback | `OMX.dji.video_decoder.avc.ffmpeg` | ~40 fps; I420 planar |

## Ports

| Component | Port | Direction | Size | Format | Buffers |
|---|---|---|---|---|---|
| decoder | 0 | in | 1920×1080 | AVC/HEVC | 16 |
| decoder | 1 | out | 1920×1080 | YUV420SP | 7 |
| sink | 0 | in (main) | 1920×1080 | YUV420SP | 7 |
| sink | 1 | in (sub) | 640×360 | YUV420SP | 7 |

The decoder input port is sized to **6 MB** by the component; allocate 16
buffers. The sink main port uses the same URL as the air-link pipeline:

```json
{"config_file":"/etc/display_frame_rate_map.json",
 "enable_aux_liveview":false,
 "sub_stream_h_offset":144,"sub_stream_v_offset":64,
 "sub_stream_width":496,"sub_stream_height":280,
 "notify_sub_stream_alive_status":true}
```

Passed as `OMX_SetParameter(sink, 0x0100000D, &hdr)`:
`u32 nSize = strlen(url)+0x0d`, `u32 nVersion = 1`, URL at offset 8.

## Setup sequence

```c
get(&dec,  "OMX.dji.video_decoder.avc.vc8000d", ...);
get(&sink, "OMX.dji.iv_renderer.yuv.extra_blending", ...);

/* input 1920x1080, output 1920x1080 YUV420SP, 7 */
cfg_port(dec, 0, 1920, 1080, OMX_VIDEO_CodingAVC, 16);
cfg_port(dec, 1, 1920, 1080, OMX_COLOR_FormatYUV420SemiPlanar, 7);

/* sink main + URL, sub 640x360 */
cfg_port(sink, 0, 1920, 1080, OMX_COLOR_FormatYUV420SemiPlanar, 7);
set_url(sink);
cfg_port(sink, 1, 640, 360, OMX_COLOR_FormatYUV420SemiPlanar, 7);

OMX_SetupTunnel(dec, 1, sink, 0);

/* Idle both, then allocate ONLY: decoder input + sink sub */
send_idle(dec); send_idle(sink);
alloc(dec, 0, 16);
alloc(sink, 1, 7);

send_executing(dec); send_executing(sink);
```

Do **not** allocate the decoder output or the sink main input: the tunnel owns
those buffers. Allocate them and the hardware decoder will stall/free-run.

## Input framing

- TCP payload: `u32le length` followed by one Annex-B access unit.
- Send the first SPS/PPS as a separate **codec-config** buffer:
  `nFlags = OMX_BUFFERFLAG_CODECCONFIG`, no `ENDOFFRAME`.
- Then send the IDR/frame AUs with `OMX_BUFFERFLAG_ENDOFFRAME`.
- Set NVENC `aud=1` and `repeat_headers=1`; hardware decoders use the AUD for
  AU boundaries and benefit from repeated SPS/PPS.
- HEVC: codec config = VPS (32), SPS (33), PPS (34).

## Output layout

Hardware decoder output:

- **linear NV12**
- `PIX_FMT_YUV420SP`, `stride = 2048`, `slice = 1080`
- `nFilledLen = 3,317,760` (`2048*1080*3/2`)

The OMX port may report `nStride = 1920`; trust `nFilledLen`:
`stride = nFilledLen / (height*3/2)`. The sink main buffer is the same size, so
the tunnel is a zero-copy handoff.

Software `avc.ffmpeg` fallback reports format 21 but emits **I420 planar**
(Y, U plane, V plane). Interleave U/V into NV12; do not treat it as interleaved.

## Host sender

- dxcam BGRA at 1920×1080, 60 fps (native; no scaling).
- NVENC: `preset=p1`, `tune=ull`, `bf=0`, `delay=0`, `zerolatency`, CBR
  30 Mbps, `aud=1`, `repeat_headers=1`, `spatial_aq/temporal_aq`.
- PyAV BGRA → yuv420p; draw the Windows cursor before conversion (DXGI does
  not include it).
- TCP `TCP_NODELAY`, framed `[u32le len][AU]`.
- Reference: `app/h264send.py` (`H264Sender`, `codec="h264"|"h265"`).

## Teardown

1. Stop feeding.
2. Decoder → Idle.
3. Sink → Idle; free the sub buffers; `OMX_FreeHandle(sink)`.
4. Free the decoder input buffers; `OMX_FreeHandle(dec)`.
5. Restore the stock UI.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `vc8000d` decodes one frame then freezes / 100k “frames”/s | output not tunnelled | `OMX_SetupTunnel(dec,1,sink,0)`; do not allocate decoder output |
| Freezes after ~8 AUs | too few decoder input buffers | 16 buffers; the port sizes to 6 MB |
| Image sheared / broken | copied with port stride 1920 but real 2048 | derive stride from `nFilledLen` |
| All colours green/purple, black/white fine | planar I420 treated as NV12 | software fallback only: interleave U/V |
| Sink `OMX_GetHandle` hangs in `eventfd_write` | fork child inherited display locks | load `hook_overlay.so` with the mod; close fds 3..1023; kill UI parent |
| 40 fps | using `avc.ffmpeg` | use `avc.vc8000d` + tunnel |
| Grey / D-Log M look | air unit / 3D LUT / display mode | power off the O4; LUT disable (`set3DLUTE`) did not change it |

## Reference implementations

- `mods/h264/h264live.c` — full tunnel, fork, stats, sub feed, codec config.
- `sdk/examples/display_sink/` — sink URL/ports/probe and the planar fallback.
- `app/n3live.py` + `app/h264send.py` — host backend/sender.
- `docs/PC-TO-GOGGLES.md` — measured findings and history.
