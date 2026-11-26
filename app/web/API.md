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

## Sparrow2 / radio (read-only)

```ts
sparrow_report() -> { ok, data: object }
sparrow_tools() -> { ok, text: string }
sparrow_console() -> { ok, text: string }
```

## Preferences (local UI only)

```ts
prefs() -> { accent: string, motion: boolean, density: string, live_scale: string }
set_pref(key: string, value: any) -> { ok: boolean }
```
