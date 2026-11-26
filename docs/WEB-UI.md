# N3 ROOT web UI (pywebview)

The desktop app runs a **Python backend + HTML/CSS/JS front-end** hosted by
`pywebview` (WebView2 on Windows). Same device code as before, with real
animations, page transitions, better typography and a professional layout.

## Run

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 app/webapp.py
```

`Start N3 ROOT.cmd` and `run.ps1` now launch the web UI and fall back to the
classic Tk app automatically if pywebview or `app/web/index.html` is missing.
The Tk app is still runnable directly:

```powershell
py -3.12 app/main.py
```

## Architecture

```
app/webapp.py          pywebview host + Api class (device-facing)
app/web/index.html     UI shell, all seven pages
app/web/styles.css     design system, layout, motion
app/web/app.js         navigation, API calls, mock mode, palette
app/web/API.md         backend contract
app/tools/ui_shot.ps1  headless screenshot helper
```

- `app/webapp.py` owns every device call (`n3ctl`, `mods`, `background`,
  `ui.live`). The static UI never talks to ADB or the root shell.
- The UI calls `window.pywebview.api.*`; see `app/web/API.md`.
- The Root Shell API (`run_shell`) blocks `/system`, verity, partitions,
  bootloader, flashing and raw block-device writes.
- `status()` caches its answer for 2 s and probes libusb + the UI process in
  parallel, so the 5 s poll costs ~1.5 s instead of ~3 s.

## Pages

| Page | Safety | What it does |
|---|---|---|
| Connection | RISKY | USB / root / ADB state, device summary, first-run checklist, all connection actions. |
| E420Z | EXPERIMENTAL | Live mirror, scale selector, FPS chips, screenshot. |
| PC Stream | EXPERIMENTAL | Desktop -> goggles: on/off toggle, encode + device stats, size/fps/quality settings. |
| Sparrow2 | SAFE | Read-only report, tool inventory, console help, doc links. |
| Root Shell | RISKY | uid 0 command prompt with history and `/system` blocking. |
| Mods & UI | EXPERIMENTAL | Install/uninstall mods with risk confirmations. |
| Logs | SAFE | Five tabs, auto-refresh, filter, copy, client-side clear. |
| Settings | SAFE | Accent, motion, density, live scale, themes, safety key, DANGER card. |

### PC Stream page

Sends this desktop into the goggles. It needs ADB, the root shell (to label the
on-device receiver) and the **Frame injection (PC stream)** mod; the page keeps
Start disabled and explains itself when one is missing. Settings are size, fps
and quality; the page shows both sides of the pipeline - sender fps/KB/s/frames
and the goggles' decode/publish timings, dropped frames and errors.

Full architecture, measured numbers and troubleshooting: [PC-STREAM.md](PC-STREAM.md).

## URL parameters (preview and screenshots)

| Parameter | Effect |
|---|---|
| `?mock=1` | Deterministic mock backend, labelled with a **MOCK** chip. |
| `?page=<id>` | Open a page directly (`connection`, `live`, `sparrow`, `shell`, `mods`, `logs`, `settings`). |
| `?motion=0` | Force reduced motion. Every animation ends immediately, so screenshots are deterministic. |

Inside pywebview the same works through the hash (`index.html#settings`).

## Verification

`webapp.py --selftest` opens the real window, waits for boot, dumps what the UI
actually rendered and closes:

```powershell
py -3.12 app/webapp.py --selftest
SELFTEST  {"mode":"host",...,"scales":[...7 labels...],"errors":[]}
SELFTEST2 {"page":"page-settings","themeOptions":6,"paletteItems":27,"errors":[]}
```

It reports the active page, the real scale list from `live_resolutions()`, the
theme list, the palette contents and any uncaught JS error. Use it after any
front-end change; `"errors":[]` is the pass condition.

## Safety boundary

- Static UI work (Claude/OpenDesign) is restricted to `app/web/`.
- No UI file receives ADB/root credentials or calls the goggles directly.
- `open_doc()` only opens files under `docs/`, and only after checking the path
  resolves inside the repo.
- `/system` writes, dm-verity changes, OTP/RPMB, flashing and RF transmit are
  out of scope. See `SAFETY.md`.

## Design

- Dark neutral surfaces, DJI purple accent, SAFE/EXPERIMENTAL/RISKY badges.
- Sliding sidebar pill, sticky blurred header, page fade + staggered cards,
  hover lift, pulsing status dots, count-up numbers, toasts, command palette.
- Live preview shows a scanline placeholder until frames arrive.
- Risk confirmations focus **Cancel**, so Enter cannot confirm a risky action.
- Motion is disabled by the Settings switch, the OS reduced-motion setting, or
  `?motion=0`.
- OpenDesign is a **design reference** for the dashboard layout and
  design-system vocabulary, not a runtime dependency. Notes: `WEB-DESIGN.md`.

## Reviewing the UI without the goggles

```powershell
# one page, default 1360x880
powershell -File app/tools/ui_shot.ps1 -Page settings

# another size
powershell -File app/tools/ui_shot.ps1 -Page live -Width 1120 -Height 720 -Out shot.png
```

The helper runs headless Edge — the same Chromium engine WebView2 uses — with
`?mock=1&motion=0`.

## Status

- [x] pywebview host + API contract
- [x] Verified WebView2 host and API bridge (`--selftest`)
- [x] Headless screenshot workflow
- [x] Designed front-end (Opus build, reviewed and wired)
- [x] Every page wired to the backend; scale list and themes come from the API
- [x] Web host is the default launcher
- [x] Live preview frames over the existing capture path
- [ ] Live preview and S2 capture verified on a connected device
