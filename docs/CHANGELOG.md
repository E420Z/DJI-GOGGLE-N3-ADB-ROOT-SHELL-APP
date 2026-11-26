# Changelog

## Unreleased — live preview fix + resolutions (2026-11-26)

- Fixed the live preview freeze after ~10 s:
  - `n3live` now writes chunked frames with a 1 MB pipe and closes the FIFO on
    any incomplete frame (no more partial-frame misalignment).
  - The app reader now uses a Windows-safe pump thread + queue, exact reads
    with timeouts, and auto-restarts/resyncs `adb exec-out` on EOF/bad header.
- Added a live resolution selector: 160×90, 240×135, 320×180, 480×270,
  640×360, 960×540, 1920×1080. Measured: ~58 fps at 160×90, ~8 fps at 640×360,
  ~0.9 fps at 1080p. Changes apply live within ~2 s.
- Rebuilt `n3live.so` (v0.2).
- Sparrow2 bulk-route console probe: custom `-J` route loaded and free `test:9`
  host locked, but the bulk send still returns `-1007`
  (`linux_bulk_write` interface 4 send timeout). No console response.

## Unreleased — Sparrow2 research (2026-11-25)

- Added the **Sparrow2** app page (read-only): firmware inventory, shipped
  console/test tools, `sdr_shell help` probe, and the factory-PC gating
  explanation.
- Documented the full Sparrow2 investigation in [`SPARROW2.md`](SPARROW2.md):
  naming, firmware inventory, `sdr_shell` protocol, factory test suite, DUSS
  routing (`-1002`/`-1007`), the factory-flag attempt + recovery, channel
  inventory (logs/dumps only), and the AMT surface (manufacturing/calibration/
  file/auth, not IQ).
- Added [`SPARROW2-EVIDENCE.md`](SPARROW2-EVIDENCE.md) with verbatim console
  errors, DUSS host list, recovery proof, channel table, firmware, and AMT
  strings.
- Added the in-app **Load findings** view and `n3_sparrow2_report.py` for a
  one-command read-only report.
- Prepared an on-device **custom `-J` bulk-route console probe**
  (`probe_n3_bulk_console.py` + experimental app button): enables the disabled
  `system_service` bulk route to `vt_gnd` over `/bulk/s2` with a free `test:9`
  source host. Dry-run verified; hardware run pending.
- Result: **no exposed AP-side IQ/ADC channel.** The console is a factory-PC
  tool. The remaining on-goggles leads are the bulk/AMT channels
  (logs/file/auth), not IQ.
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
