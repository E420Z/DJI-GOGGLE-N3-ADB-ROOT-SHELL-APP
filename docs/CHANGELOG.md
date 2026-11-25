# Changelog

## 1.0.0 — 2026-11-25

- Labelled experimental/crash-prone areas in the app, plugin manifests, README,
  and `docs/EXPERIMENTAL.md`. The N3 Menu is **experimental/beta**; the
  `displayFrame` hooks that black-screened are compile-time **off**.
- Marked the GitHub release as a **prerelease** and included recovery steps.

- New CustomTkinter control deck: Connection, E42OZ, Root Shell, Mods & UI,
  Logs, Settings.
- Embedded live preview from the goggles UI: 160×90, ~59 fps (verified).
- Full-resolution screenshots from the app (safe thread-only capture).
- Embedded root shell console with history.
- One-click **Recover stock UI**.
- Mods page with install/remove, purple/menu-only themes, custom background,
  and custom menu.
- Plugin manifests for n3menu, n3live, capture, paint.
- In-goggles SDK (`sdk/`) with template and build script.
- Linux ADB backup/recovery CLI (`linux/n3backup.py`).
- Docs: exploit, safety, live stream, overlay/SDK, architecture, troubleshooting.
- Git repo, CI smoke test, README with screenshots.

Safety: session-only root via the stock `dji_blackbox` path; no `/system`,
dm-verity, OTP/RPMB, or bootloader changes.
