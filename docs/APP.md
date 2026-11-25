# N3 ROOT app guide

## Pages

### Connection
- **USB / ROOT / ADB** status cards.
- **Enable ADB** switches the stock USB composition to include ADB.
- **Start root** opens the `dji_blackbox` shell on `192.168.60.2:4444`.
- **Stop root** kills the session shell.
- **Recover stock UI** restarts `dji_glasses` (the black-screen escape hatch).
- **Restart patched UI** starts the themed UI with the installed mods.

### E42OZ
- **Start live** restarts the goggles UI with `n3live` and `hook_capture`, then
  streams 160×90 at ~57 fps into the app.
- **Screenshot** captures a full 1920×1080 frame via the safe dmabuf hook.
- **Record 10s** saves a GIF of the live preview.
- Quick actions: purple theme, menu-only theme, custom menu, background, recover.

### Root Shell
Embedded console. Each command runs as uid 0 in `dji_services` in a fresh
shell. Use `cd /path && command` if you need a working directory. Up/Down cycles
command history.

### Mods & UI
- Lists built-in and plugin mods with install/remove.
- Theme presets use `theme_builder` + `n3ctl.install_theme`.
- Background uses `background.install`.
- **Start UI with installed mods** pushes the loader list and restarts.
- **Revert to stock** removes the N3 theme/mod files and starts stock.

### Logs
Tail `natartos.log`, `n3mods.log`, `dji_glasses.log`, `n3_texttint.log`.

### Settings
Paths, auto-refresh, restore-USB-on-exit, version/safety notes.

---

## Common workflows

### First connection
1. Power the goggles and connect USB.
2. Connection → **Start root**.
3. Connection → **Enable ADB** (needed for live/screenshot).
4. E42OZ → **Start live**.

### Purple theme
Mods & UI → **Apply Purple theme**. The app builds a patched
`libew_gls.so` from your local stock lib and restarts the UI. The stock
`libew_gls_stock.so` is not committed to git; put it in `app/assets/`.

### Custom background
Mods & UI or E42OZ → **Choose background** → pick a 16:9 image. The app creates
normal + idle JPEGs and the `n3bg` hook.

### In-goggles menu
Mods & UI → install **N3 Menu** → **Start UI with installed mods**. The menu
window is composited into the live buffer. Buttons: short up/down move, hold
DOWN = OK, hold UP = exit. Stock keys/touch are suppressed while it is open.

### Screenshots
Use **E42OZ → Screenshot**. Full 1920×1080 PNGs land in `app/state/shots/`.
The capture is a thread-only dmabuf read; it never suppresses a display frame.

---

## Troubleshooting

**Black screen** → Connection → **Recover stock UI**. A power cycle also
restores stock. Nothing is installed in the boot chain.

**Live preview 0 fps** → ADB must be on; the UI must be restarted with `n3live`
(the Start live button does both). Check Logs → `natartos.log` for
`[live] thread: start`.

**Theme build fails** → `app/assets/libew_gls_stock.so` is missing. It is
intentionally gitignored; copy the stock lib from your device/firmware.

**No root shell** → the libusb0 driver must be bound to the goggles' blackbox
interface (Zadig). Check Connection → USB DEVICE.

**ADB not found** → install platform-tools and put `adb.exe` in `PATH` or
`C:\platform-tools`.

**Menu mod black-screens** → this repo ships the conservative build with
`DisplayEngine` hooks disabled. Recover stock UI, then reinstall from
`app/plugins/n3menu`.

---

## Development

- Add a mod: `app/plugins/<id>/plugin.json` + `files/*.so` (see
  `app/plugins/README.md`).
- Add a page: `app/ui/pages/` and register it in `app/main.py`.
- SDK: `sdk/` (`n3app.h`, `n3app.c`, `build.ps1`, template).
- Debug tools: `app/tools/`.
