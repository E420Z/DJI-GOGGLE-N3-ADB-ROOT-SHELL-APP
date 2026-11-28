# Fast PC → goggles video (1080p60)

Status: **working at 1080p60** through the hardware decoder tunnel
(`OMX.dji.video_decoder.avc.vc8000d` → `extra_blending`). The software
`avc.ffmpeg` decoder caps at ~40 fps; its planar I420 output is documented
below as the fallback.

## Hardware 1080p60 tunnel (current path)

The software `OMX.dji.video_decoder.avc.ffmpeg` decoder is CPU-bound at about
40 fps even decode-only. The hardware `OMX.dji.video_decoder.avc.vc8000d`
decodes 1080p60, but only when its output is **tunnelled** into the display
sink. Standalone it free-runs/repeats the last frame and holds input buffers.

Proven sequence:

1. Get `OMX.dji.video_decoder.avc.vc8000d` and
   `OMX.dji.iv_renderer.yuv.extra_blending`.
2. Decoder input 0: 1920×1080 AVC, 16 buffers (the component sizes it 6 MB).
   Decoder output 1: 1920×1080 YUV420SP, 7 buffers.
3. Sink main 0: 1920×1080, 7 buffers, URL; sub 1: 640×360, 7 buffers.
4. `OMX_SetupTunnel(decoder, 1, sink, 0)`.
5. `Idle` both; allocate the **decoder input** and **sink sub** buffers only
   (the tunnel owns the decoder output / sink main buffers); `Executing` both.
6. Feed decoder input AUs; feed the sub port black frames.
7. Teardown: decoder Idle → sink Idle/free → FreeHandle.

Hardware output is **linear NV12, stride 2048, nFilledLen = 3,317,760**
(2048×1080×1.5), which matches the sink exactly; the tunnel copies nothing.

Measured with the desktop sender:

```
tunnel=0  idle=1  sink idle=1  exec=1  sink exec=1
60.0 fps, 29.9 Mbps, NVENC encode ~7.4 ms, 856 frames / 14 s
```

The sender sets `aud=1` and `repeat_headers=1`; the mod also feeds the first
SPS/PPS as an `OMX_BUFFERFLAG_CODECCONFIG` buffer before the IDR.

H.265 is tested on the same tunnel: `OMX.dji.video_decoder.hevc.vc8000d`
with `hevc_nvenc` at 20 Mbps, **60.1 fps** (360 device frames / 6 s, no drops).
H.264 remains the default; H.265 is the efficiency/bitrate option.

## Direction: air link vs USB

- The **air link is air unit → goggles** (downlink). The goggles is the
  receiver; the PC is not a transmitter on that link.
- PC → goggles is **USB** (RNDIS/bulk) → H.264 decoder →
  `OMX.dji.iv_renderer.yuv.extra_blending` → panel. This is the same display
  sink the air-link liveview uses.
- `libOmxUvcSink.so` / `uvc,adb` is a **UVC output** (goggles → PC), not a
  PC → goggles input.

## Working pipeline

```
PC desktop (DXGI/dxcam)
  -> BGRA -> yuv420p (NVENC H.264, low-latency)
  -> TCP 5572 framed Annex-B
  -> OMX.dji.video_decoder.avc.ffmpeg
  -> decoder output: Y + U plane + V plane (I420 planar!)
  -> interleave U/V -> sink NV12 buffer
  -> OMX.dji.iv_renderer.yuv.extra_blending
  -> lcdc video plane 4 -> panel
```

Measured: **~40–58 fps**, 0 sink drops, video plane scanning at 60 Hz.

## Sink config (proven)

| Port | Size | Format | Buffers |
|---|---|---|---|
| 0 main | 1920×1080 | YUV420SP | 7 |
| 1 sub | 640×360 | YUV420SP | 7 |

URL via `OMX_SetParameter(component, 0x0100000D, &buf)`:

```json
{"config_file":"/etc/display_frame_rate_map.json",
 "enable_aux_liveview":false,
 "sub_stream_h_offset":144,"sub_stream_v_offset":64,
 "sub_stream_width":496,"sub_stream_height":280,
 "notify_sub_stream_alive_status":true}
```

Struct: `u32 nSize = strlen(url) + 0x0d`, `u32 nVersion = 1`, URL at offset 8.

The sink accepts the URL (`url ret=0`) and keeps 7 buffers per port. Its main
input buffer is **3,317,760 bytes**: `stride = align256(width) = 2048`,
`slice = 1080`, Y at 0, UV at `stride*slice = 2,211,840`, UV stride 2048.
`nFilledLen = stride*slice*3/2`.

## The decoder is planar I420 (key finding)

The decoder port definition reports `eColorFormat = 21`
(`OMX_COLOR_FormatYUV420SemiPlanar`) and `nFilledLen = 3,110,400`, but the
actual buffer is **I420 planar**:

- Y: `1920×1080` at offset 0
- U: `960×540` at offset `1920*1080`
- V: `960×540` at offset `1920*1080 + 960*540`

Proof with a solid red frame (BT.601: U≈90, V≈240):

```
first half of the "UV" region:  mean 90.2   (U plane)
second half:                    mean 239.3  (V plane)
```

Treating that as interleaved NV12 gives U/V pairs mixed from both planes:
black/white (U=V=128) look fine, every real colour goes green/purple. The fix
is to interleave explicitly:

```c
const unsigned char *u = yuv + W * H;
const unsigned char *v = u + (W / 2) * (H / 2);
for (int r = 0; r < H / 2; r++) {
    unsigned char *d = dst_uv + r * dst_stride;
    const unsigned char *ur = u + r * (W / 2);
    const unsigned char *vr = v + r * (W / 2);
    for (int x = 0; x < W / 2; x++) {
        d[2 * x]     = ur[x];   /* U */
        d[2 * x + 1] = vr[x];   /* V */
    }
}
```

The sink takes NV12 (U then V); no byte swap is needed after this.

## Display plane / UI release

dmesg from the live sink:

- **video plane 4**: `alpha 255, order 0`, `lcdc display 1st frame` at 60 Hz.
- **UI gfx0 plane 5**: `order 2` — the home screen covers the video plane.
- backlight `aw99703-bl` at max (2047); not the problem.

The proven release:

1. Start the UI with **both** `hook_overlay.so` and `n3h264live.so`. Without
   `hook_overlay.so`, `OMX_GetHandle(extra_blending)` in the fork child can
   stall forever in `eventfd_write` inside the renderer thread.
2. In the mod, `fork()`; in the child `setsid()`, `prctl(PR_SET_NAME)`, close
   inherited fds 3..1023, **kill the UI parent**, then open the sink
   immediately (the probe order).
3. Open the sink while the display service is healthy; then feed frames.
4. Restore the stock UI after the session (`start_stock_ui`).

A child forked from the UI inherits the UI's display/gfx fds; closing them and
killing the parent releases gfx0.

## Decoder callback must be decoupled

Calling `OMX_EmptyThisBuffer` on the sink from inside the decoder's
`FillBufferDone` callback stalls the decoder after ~1 s. Copy the decoded frame
into a small queue and feed the sink from a **separate thread**. One queued
frame (drop if busy) is enough for live video.

## Encoder (PC side)

- NVENC H.264, `preset p1`, `tune ll`, `bf 0`, `zerolatency`, CBR 30 Mbps,
  `spatial_aq/temporal_aq`, 1080p60.
- dxcam captures 2048×1536 (4:3) on this machine; it is **stretched** to
  1920×1080 by request (the full-screen look).
- dxcam does not capture the cursor; the sender alpha-blends the Windows
  cursor bitmap (`GetCursorInfo`/`GetIconData`) into each frame.
- dxcam frames are BGRA; PyAV converts to yuv420p.

## Measured device stats

`/data/local/tmp/h264live.stat`:

```
frames=<decoded> sink=<fed> sinkempty=<returned> drop=<no-buffer> qdrop=<queue-full>
```

Typical: `frames≈sink`, `drop=0`, `qdrop=0–1` at 40–58 fps.

## Things that did **not** fix it

- U/V byte swapping (made it "look better" but still wrong; the real bug was
  planar vs interleaved).
- Disabling the sink's 3D LUT / gamma via
  `DisplaySink::set3DLUTE(false, "")` — no visual change.
- `OMX_IndexParamColorSpace` — both decoder and sink return
  `0x8000101A` (unsupported).
- Different sink UV strides/offsets — the sink buffer layout was already
  correct; the decoder source layout was wrong.

## H.264 vs H.265

- H.265/HEVC is ~30–50% more efficient; the goggles' air-link decoder is HEVC.
- H.264 at 20–30 Mbps is already sufficient for USB and the desktop.
- HEVC is a quality/bitrate optimisation, not a prerequisite.

## Safety

- No RF transmit, no air-link injection.
- No `/system` writes; the sink is configured at runtime.
- Bound every session; restore the stock UI on exit.
- The O4 air unit should be off for the cleanest PC → goggles test (it uses the
  same display sink and can hold a colour/LUT mode).
