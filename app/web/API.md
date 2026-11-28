# N3 ROOT web UI — API contract (v1)

The UI is loaded by `app/webapp.py` in a `pywebview` window. It calls Python via:

```js
const api = window.pywebview && window.pywebview.api;
await api.status();
```

Every method returns a JSON-serialisable object. Long operations may take
seconds; show a busy state and a toast when they finish.

## Status

```ts
status() -> {
  version: string,
  ui: boolean,          // patched UI process alive
  patched: boolean,     // /vendor/dji_glasses_patched running
  root: boolean,        // root shell TCP reachable
  adb: boolean,         // adb device online
  theme: string,        // "stock" | "purple" | "menu-only"
  background: boolean,  // custom background installed
  menu: boolean,        // stock menu row installed
  pid: string,
  transport: string,    // "USB" | "ADB" | "root" ...
  serial: string,       // masked by the backend
  device: string        // "DJI Goggles N3"
}
```

## Actions (all return `{ok: boolean, message: string}`)

```ts
enable_adb()
start_root()
stop_root()
start_ui()
recover_stock()
open_terminal()
open_doc(path: string) -> { ok, message }        // read-only, docs/ only
run_shell(command) -> { ok, message, output }  // RISKY, /system is blocked
```

## Mods

```ts
mods_list() -> { mods: [{
  id, name, version, type, risk, installed, experimental,
  description, notes
}] }
install_mod(id) -> { ok, message }
uninstall_mod(id) -> { ok, message }
```

## Themes

```ts
themes() -> { themes: string[] }       // e.g. ["Purple", "Menu only", "Stock"]
apply_theme(name) -> { ok, message }
```

## Logs

```ts
logs() -> {
  natartos: string,
  n3mods: string,
  ui: string,
  capture: string,
  web: string        // Python host notes
}
```

## Live preview

```ts
live_start(scale_label: string) -> { ok, message }  // "160x90 (fast)", "640x360", ...
live_stop() -> { ok, message }
live_resolutions() -> { resolutions: string[], default: string }
live_frame() -> {
  ok: boolean,
  image: string,       // "data:image/jpeg;base64,..." (empty when no frame)
  width: number, height: number, fps: number
}
capture_screen() -> { ok, message, image: string, path: string }
```

## PC → Goggles (hardware tunnel)

```ts
pcvideo_info() -> {
  ok, state: "idle" | "starting" | "live" | "error", message,
  stats: { fps, kbps, bitrate, codec, size, frames, bytes,
           encode_ms, drops, device_frames, input_empty },
  device: { root, ui, stat: {...} },
  display: { current: {w,h,hz}, saved: {w,h,hz}|null, switched, auto,
             target: "1920x1080@60" },
  settings: { codec: "h264" | "h265", bitrate, cursor, auto_display, size, fps },
  notes: string[]
}
pcvideo_start(codec, bitrate, cursor, auto_display) -> { ok, message, stats }
pcvideo_stop() -> { ok, message, stats }
pcvideo_set(codec, bitrate, cursor, auto_display) -> { ok, message, settings }
pcvideo_display(switch_now, restore) -> { ok, message, display }
```

`pcvideo_start` pushes `n3h264live.so`, starts the patched UI with
`hook_overlay.so`, arms the `vc8000d → extra_blending` tunnel, and starts the
NVENC sender on TCP 5572. If `auto_display` is true it saves the current PC
mode and switches to 1920×1080 @ 60 Hz first; Stop restores it. It needs the
root shell and the mod loader. Everything it writes is under
`/data/local/tmp` and `/vendor` (the module). Stop removes the triggers and
restores the stock UI.

## Goggles stream (goggles → PC)

```ts
gstream_info() -> {
  ok, state: "idle" | "starting" | "live" | "error", message,
  stream_url,                       // http://127.0.0.1:8771/stream.mp4 when live
  stats: { fps, kbps, frames, dropped, width, height, latency_ms, bytes },
  device: { mod, fills, sent, drops, props },
  ffmpeg: { available, path }
}
gstream_start() -> { ok, message, state, stream_url? }
gstream_stop()  -> { ok, message, stats }
```

`gstream_start` deploys `n3videoout.so` to `/vendor`, restarts the goggles UI
only if the mod is not already mapped, turns the vendor liveview properties on,
and connects to TCP 5571. The Python side remuxes with ffmpeg to fragmented MP4
and serves it on **127.0.0.1:8771** for the page. `gstream_stop` removes the
marker, clears the properties, and stops ffmpeg. No `/system` writes; see
[`docs/GSTREAM.md`](../docs/GSTREAM.md).

## Sparrow2 / radio (read-only)
```ts
sparrow_report() -> { ok, data: object }
sparrow_tools() -> { ok, text: string }
sparrow_console() -> { ok, text: string }
```

### S2 receiver capture (experimental, receive-only)

```ts
s2_probe() -> { ok, message, text }                  // SAFE: inventory only
s2_capture(iface, seconds) -> { ok, message, text, files: [{ name, size }] }
s2_stop() -> { ok, message, text }
s2_pull(name) -> { ok, message, path, size, head }   // writes on the PC only
s2_liveview(action) -> { ok: false, message }        // link start/stop not wired
```

`s2_capture` runs `/data/local/tmp/s2cap.sh`, which is installed by the
**S2 video capture** mod. It writes only under `/data/local/tmp/s2cap` and never
starts the radio link.

## Preferences (local UI only)

```ts
prefs() -> { accent: string, motion: boolean, density: string, live_scale: string }
set_pref(key: string, value: any) -> { ok: boolean }
```
