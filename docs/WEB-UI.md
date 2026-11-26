# N3 ROOT web UI (pywebview)

The desktop app is moving from CustomTkinter to a **Python backend + HTML/CSS/JS
front-end** hosted by `pywebview` (WebView2 on Windows). This gives real
animations, page transitions, better typography and a professional layout
without changing the device code.

## Run

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 app/webapp.py
```

The classic Tk app remains available as a fallback:

```powershell
py -3.12 app/main.py
```

## Architecture

```
app/webapp.py          pywebview host + Api class (device-facing)
app/web/index.html     UI shell
app/web/styles.css     design system
app/web/app.js         navigation, API calls, mock mode
app/web/API.md         backend contract
```

- `app/webapp.py` owns every device call (`n3ctl`, `mods`, `background`,
  `ui.live`). The static UI never talks to ADB or the root shell.
- The UI calls `window.pywebview.api.*`; see `app/web/API.md`.
- Without pywebview, `app.js` renders deterministic mock data so the page can
  be reviewed in a browser (`?mock=1`).
- The Root Shell API (`run_shell`) blocks `/system`, verity, partitions,
  bootloader, flashing and raw block-device writes.

## Safety boundary

- Static UI work (Claude/OpenDesign) is restricted to `app/web/`.
- No UI file receives ADB/root credentials or calls the goggles directly.
- `/system` writes, dm-verity changes, OTP/RPMB, flashing and RF transmit are
  out of scope. See `SAFETY.md`.

## Design

- Dark neutral surfaces, DJI purple accent, SAFE/EXPERIMENTAL/RISKY badges.
- Page transitions, animated sidebar, hover cards, pulsing status, toasts,
  command palette, live-preview chrome, monospace logs.
- OpenDesign is used as a **design reference** for the dashboard layout and
  design-system vocabulary, not as a runtime dependency.

## Reviewing the UI without the goggles

Headless Edge (the same Chromium engine WebView2 uses) can screenshot the
static page:

```powershell
msedge.exe --headless=new --window-size=1360,880 `
  --allow-file-access-from-files `
  --screenshot=app/state/web.png app/web/index.html
```

## Status

- [x] pywebview host + API contract
- [x] Verified WebView2 host and API bridge
- [x] Headless screenshot workflow
- [ ] Designed front-end (Claude/Opus build)
- [ ] Wire every page action and live preview
- [ ] Make the web host the default launcher
