# Changelog

## Unreleased — Sparrow2 research (2026-11-25)

- Added the **Sparrow2** app page (read-only): firmware inventory, shipped
  console/test tools, `sdr_shell help` probe, and the factory-PC gating
  explanation.
- Documented the full Sparrow2 investigation in [`SPARROW2.md`](SPARROW2.md):
  naming, firmware inventory, `sdr_shell` protocol, factory test suite, DUSS
  routing (`-1002`/`-1007`), the factory-flag attempt + recovery, channel
  inventory (logs/dumps only), and the AMT surface (manufacturing/calibration/
  file/auth, not IQ).
- Result: **no exposed AP-side IQ/ADC channel.** The console is a factory-PC
  tool; the practical analog route is an external receiver into the display
  video plane.
- Added portable probes: `probe_n3_factory_*.py`, `probe_n3_amt_proto.py`,
  `probe_n3_sdr_console*.py`.

## 1.0.0 — 2026-11-25

- Labelled experimental/crash-prone areas in the app, plugin manifests, README,
  and `docs/EXPERIMENTAL.md`. The N3 Menu is **experimental/beta**; the
  `displayFrame` hooks that black-screened are compile-time **off**.
- Published **v1.0.0 as a private experimental prerelease** with
  `N3-ROOT-v1.0.0.zip`.
- Verified privacy: repo/release/asset return 404 without authentication.

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
