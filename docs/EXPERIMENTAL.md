# Stability and experimental features

N3 ROOT is experimental software running on a rooted consumer device. Some
features can break rendering or leave the UI in a bad state. This page is the
single source of truth for what is stable and what is risky.

## Quick recovery

If the screen goes black or freezes:

1. App → **Connection → Recover stock UI**
2. Or power-cycle the goggles (nothing is installed in the boot chain)
3. Or from a terminal:
   `py -3.12 -c "import sys; sys.path.insert(0,'app'); import n3ctl; n3ctl.start_stock_ui()"`

## Status table

| Area | Status | Crash/bug history | Notes |
|---|---|---|---|
| Control deck UI | **Stable** | — | Builds and runs; smoke-tested. |
| Live preview (`n3live`) | **Stable** | — | Verified 160×90, ~59 fps. Read-only. |
| Screenshots (`hook_capture`) | **Stable** | — | Thread-only dmabuf read; no display detour. |
| Theme patches | **Low risk** | — | Reversible; can leave visual artifacts until revert. |
| Custom background | **Low risk** | — | Reversible; needs the `n3bg` hook. |
| Root shell / ADB | **Stable on Windows** | — | Session-only; power-cycle restores stock. |
| **N3 Menu app** (`n3menu`) | **Experimental / beta** | A previous build black-screened on 2026-11-25. | The shipped build is the conservative compositor build. Long-press 5-way up opens/closes; short center selects; short up/down navigates; Back goes back. Power has no input event. Recover stock UI if needed. |
| **Paint overlay** (`paint`) | **Experimental proof** | — | Minimal compositor demo; not a user app. |
| Legacy natartos G3 `menu` / `popen` / `template` | **Removed** | G3-era vtable/menu code; unsafe on N3. | Removed from the app catalog and repo assets. |
| Linux root-shell exploit | **Not implemented** | — | The app/exploit path is Windows-only. Linux uses ADB backup/recovery. |

## Known limitations

- The N3 menu is one window; no full-screen apps yet.
- The menu's raw touch parser is implemented but not fully verified; buttons are
  the reliable input.
- Touch/key suppression uses EW BSP hooks. If a hook fails to install, the
  stock UI may also react to input.
- Live preview restarts the goggles UI; it is not a passive capture.
- The 104 MB stock `libew_gls.so` and `dji_glasses_vendor` are not in git; theme
  building requires them locally.

## Reporting a bug

Open a GitHub issue with:

- what you clicked,
- whether **Recover stock UI** fixed it,
- `dji_glasses.log` / `natartos.log` if the screen was black,
- goggles firmware and app version.

Do not include personal data or DJI account details.
