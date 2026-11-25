# N3 UI debug toolkit

Date: 2026-11-25. Owner's device. Debug helpers only: capture is read-only, all
tooling restores stock USB when it finishes.

Builds on `DEBUG-SCREENCAP-N3.md` (verified capture-only dmabuf hook).

## Commands

`SDR findings/tools/debug_ui.py`

```
py -3.12 debug_ui.py shot [--redeploy]
py -3.12 debug_ui.py logs [--lines N] [--errors]
py -3.12 debug_ui.py diff BEFORE.png AFTER.png [--out X.png]
py -3.12 debug_ui.py session [--redeploy]
py -3.12 debug_ui.py watch [--seconds N]
py -3.12 debug_ui.py press --key BACK|ENTER [--yes]
```

- `shot` — one screenshot (delegates to `debug_screencap.py`).
- `logs` — tail `natartos.log`, `n3mods.log`, `n3_texttint.log`,
  `dji_glasses.log`; `--errors` filters error/crash/denied lines.
- `diff` — host-only pixel diff, prints changed-pixel % and bbox, writes a red
  heatmap. Use it to confirm a theme/colour change actually landed.
- `session` — the edit→test loop: optional redeploy, restart UI, capture,
  print health (`ui_state`) and error logs, restore stock USB.
- `watch` — watchdog: polls the UI pid; if the UI dies it dumps logs, restarts
  the patched UI with the capture hook, and keeps watching. Restores USB on exit.
- `press` — guarded kernel key injection. **Dry-run by default**; needs `--yes`.
  Only `BACK`/`ENTER` are allowed unless you pass `--raw CODE`.

## Input facts (read-only discovery)

- `/dev/input/event0` = `gpio_keys`, the only physical buttons the device
  advertises. Key bitmap `40000000 0 10000000` decodes to exactly:
  - `KEY_BACK` = **158**
  - `KEY_ENTER` = **28**
- `/dev/input/event1` = `ext_touch` (absolute touch).
- `/dev/input/event2` = `ext_key`, `/dev/input/event3` = `omc_keys`
  (synthetic key sinks that advertise nearly all codes).
- `getevent` ioctls are **denied** by SELinux for the root shell, but
  `sendevent` **writes succeed**. The root shell runs as `u:r:dji_services:s0`.
- The natartos `mod_input` path (calling `CoreRoot_DriveKeyboardHitting` from a
  worker thread) is **not safe** and is not used here: it races EW's
  single-threaded UI and can hang the device. Kernel `sendevent` goes through
  the normal input path instead.

## What this makes easier

- Theme/colour/icon work: change files, `session`, then `diff` against the
  previous shot.
- Catching crashes: `watch` restarts the UI and shows the last error lines,
  instead of leaving a black screen.
- Log-driven debugging: `logs --errors` immediately after a restart.
- Scripted navigation: `press` can open/close menus once the key behavior is
  confirmed, so a screenshot can be taken of a specific screen.

## What it does NOT solve

- **Displaying a custom app/menu on the goggles.** Screenshots observe the
  stock/patched UI; they do not add a new surface. A custom app still needs a
  working display path — the N3-safe copy-on-push overlay in
  `DISPLAY-OVERLAY-N3.md`.
- **Mapping every menu action.** We have BACK/ENTER on event0; touch navigation
  codes are not mapped yet. Confirm key behavior before scripting it.

## Safety

- No `/system` writes, no dm-verity/partition, no OTP/RPMB, no bootloader.
- Capture hook is pass-through (never suppresses frames).
- `press` defaults to dry-run; BACK is the safest key; avoid repeated ENTER
  until its behavior is confirmed.
- Every command restores stock USB and stops the root shell when it exits.
- `watch` keeps ADB up during the watch and restores it at the end.
