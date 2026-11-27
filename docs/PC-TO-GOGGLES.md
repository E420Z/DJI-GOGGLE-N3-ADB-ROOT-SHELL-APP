# Fast PC → goggles video (1080p60)

Status: **static research.** The transport and decoder are proven; the blocker
is the display sink configuration, not the USB link.

## Direction: air link vs USB

- The **air link is air unit → goggles** (downlink). The goggles is the
  receiver; the PC is not a transmitter on that link.
- Sending PC video “through the air link” would require feeding the air unit’s
  camera/encoder or transmitting a DJI-compatible signal from the PC. There is
  no supported path for that, and RF transmit is outside this project.
- The fast PC → goggles path is **USB** (RNDIS/bulk) → vendor decoder →
  `OMX.dji.iv_renderer.yuv.extra_blending` → panel. It uses the **same display
  sink** as the air-link liveview.
- `libOmxUvcSink.so` / the `uvc,adb` composition is a **UVC output** path
  (goggles appears as a camera to a host), not a PC → goggles video input.

So the useful work is the display sink, not the air link.

## The target sink

`extra_blending` and `liveview` are implemented by
`libOmxLiveDispSink.so`. The air-link pipeline
(`latency_first_lvpipe.json`) configures:

| Port | Size | Format | Buffers |
|---|---|---|---|
| 0 (main) | 1920×1080 | YUV420SP | 7 |
| 1 (sub) | 640×360 | YUV420SP | 7 |

The sink `url` is:

```json
{
  "config_file": "/etc/display_frame_rate_map.json",
  "enable_aux_liveview": false,
  "sub_stream_h_offset": 144,
  "sub_stream_v_offset": 64,
  "sub_stream_width": 496,
  "sub_stream_height": 280,
  "notify_sub_stream_alive_status": true
}
```

`/system/etc/display_frame_rate_map.json` exists and maps, for example,
`real_fps 60.0000 -> DUSS_DISP_RES_1920X1080_60_0000HZ`.

## Why the earlier probe was black

`rendprobe` set **both** ports to 1920×1080 and passed **no `url`**. The sink
therefore did not get the main/sub geometry, the aux-liveview setting, or the
timing map. It accepted and returned buffers, but displayed nothing.

## How the pipeline passes the URL

`PipeBuilder::setNodeUrl` builds a small struct and calls:

```c
OMX_SetParameter(component, 0x0100000D, &buf);
```

The struct starts with:

```
u32 nSize   = strlen(url) + 0x0d
u32 nVersion = 1
char url[]  // at offset 8, NUL-terminated
```

That is the parameter the probe must add.

## Next probe (static plan, then bounded on device)

1. Open `OMX.dji.iv_renderer.yuv.extra_blending`.
2. Set the URL parameter `0x0100000D` with the JSON above.
3. Configure port 0 as 1920×1080 NV12, 7 buffers.
4. Configure port 1 as 640×360 NV12, 7 buffers (feed black).
5. Feed a 1920×1080/60 moving pattern on port 0.
6. If still black, set the display config:
   - `OMX_CONFIG_RECTTYPE` via `setProcessAera`
   - `OMX_FRAMESIZETYPE` (`userWantedScreenConfig`)
   - the display index (`setDisplayIndex`/`getExtensionIndex`)
   - inspect `duss_hal_display_*` return values and `display_timing`.
7. Only after a visible 1080p60 pattern, feed the H.264 decoder output.

## H.264 vs H.265

- H.265/HEVC is **more efficient** (~30–50% at the same quality). The goggles’
  air-link decoder is HEVC, so the hardware is natively good at it.
- The current `h264live` path uses an H.264 decoder component; HEVC may need a
  different component/MIME (`video/hevc`, `wlvdec`/`libwl_codec`) and the
  corresponding SPS/PPS handling.
- NVENC HEVC at 1080p60 low-latency (`-tune ll`, `-bf 0`, `-delay 0`) is a
  good test once the sink is visible.
- H.264 at 20 Mbps is already sufficient for USB; HEVC improves quality/bitrate
  headroom, but **does not fix the black sink**.

## Suggested order

1. Fix `extra_blending` with the URL/port config above (H.264 pattern).
2. Measure 1080p60 and end-to-end latency.
3. Switch the sender to HEVC and compare quality/latency/bitrate.
4. Keep the air link out of the PC → goggles path; it is a downlink.

## Safety

- No RF transmit, no air-link injection.
- No `/system` or `/vendor` writes; the sink is configured at runtime.
- Bound every probe (seconds), restore the stock UI on exit.
