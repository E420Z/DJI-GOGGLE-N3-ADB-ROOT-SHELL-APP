# Custom apps / menus on the N3 — architecture decision

Date: 2026-11-25. Question: for custom app + UI + menu work, is building an
SDK the best approach, or something else?

## Short answer

**Not an SDK first.** The blocker is the N3 *runtime* (display + input + menu
surface), not the API. Build one working vertical slice, then extract a thin
SDK from it. An SDK designed before the runtime works would encode guesses.

Also: **natartos is already a proto-SDK**:

- `natartos-src/include/natartos_common.h`: freestanding syscall wrappers,
  logging, vtable patching, flag files, and `natartos_menu_register()`.
- `natartos-src/mods/template/` + `mod.json` manifest: mod packaging.
- `n3mods.so` loader: resolves and loads mods into `dji_glasses`.

So the work is to make that layer **work on N3**, then formalize it, not to
start a new framework.

## Why a normal Android app SDK is the wrong model

- This DJI image has no launcher/WindowManager path for third-party apps.
- `dji_glasses` owns the DUSS display and pushes frames directly
  (`duss_hal_display_push_frame`); the UI is Embedded Wizard, single-threaded.
- SELinux is enforcing; `/system` is off-limits.
- A separate app would fight the compositor for the display and likely get no
  surface. High effort, low odds.

## Options

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. In-process mod (natartos model)** | LD_PRELOAD `.so` into `dji_glasses`; copy-on-push frames; read evdev | Reuses display/input/theme; small; no app framework needed | Crash takes down UI; ABI coupling; EW is single-threaded |
| B. Separate Android process | Own Activity/surface | Clean isolation | No launcher/WM/display path; likely not viable |
| C. Patch EW UI/resources | Compile a page into the UI | Most native | Needs DJI internals/signing; highest risk |
| D. External companion | Phone/PC renders, goggles just display/control | Safest | Not "in-goggles" |

**Recommendation: A**, with the capture/log/diff/watch toolkit for safety and a
watchdog for crash recovery.

## What "the SDK" should be (later)

A thin in-process mod SDK, not an Android SDK:

- lifecycle: `init`, `tick`, `exit`; version + capability check against loader.
- display: acquire surface, format/stride, present(frame), double-buffer.
- input: subscribe evdev (BACK=158, ENTER=28, touch), timers, main loop.
- menu: extend `natartos_menu_entry` (id, label, icon, action).
- services: logging, config, health/crash guard.
- packaging: `mod.json`, install/uninstall, ABI version.
- tooling: template, **host simulator**, tests, screenshot/diff harness.

For many "custom menu" needs, a **declarative menu entry + a render callback**
is enough; a full SDK is only needed for real apps.

## Toolchain reality

- Mods loaded into `dji_glasses` must be **bionic/arm64** if they use libc,
  pthreads, or malloc. The current hooks are freestanding syscall-only, which is
  why `zig cc -nostdlib` works.
- For an SDK with threads/heap: install the **Android NDK** (absent now) or keep
  the mod freestanding and use raw syscalls.
- Static musl binaries are fine for standalone tools, not for in-process mods
  that import libc symbols.

## Phased plan

0. **Done**: capture/logs/diff/session/watch; BACK/ENTER key map discovered.
1. **Done (2026-11-25)**: on-screen window — composites into the live dmabuf,
   backs up and restores the window area, never suppresses frames. Proven with a
   paint test and the `HELLO` SDK template. See `PAINT-OVERLAY-N3.md`.
2. **Next**: menu surface — register one entry on N3; open the window from it;
   return to the stock UI. Touch mapping for lists is still open.
3. **SDK v0.1 (started)**: `n3sdk/n3app.h` + `n3app.c` + template + build
   script. Port the GFSK monitor to it and add a host simulator.
4. **Freeze v1**: after 2 real apps, version the ABI and document it.

Note: the working design does **not** copy into `frame_buf` (that is only a
~2 MB descriptor). It composites into the 8,294,400-byte `/dmabuf:` surfaces,
which is what the display actually scans out.

## Safety invariants

- Never suppress the real display push; copy-on-push only.
- Never call EW APIs from a worker thread.
- No `/system`, verity, OTP/RPMB, or bootloader changes.
- Watchdog + capture tooling to recover from crashes during development.
