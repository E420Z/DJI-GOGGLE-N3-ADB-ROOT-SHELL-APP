# Changelog

## Unreleased - recorder test + PC-stream packaging (2026-11-26)

- Bounded omx_recordtest test: init + record start succeed against the 1080p
  display channel, then a **segfault on stop/mux**; no file produced; device
  unaffected. The factory wrapper also does a DUML route change and an I2C mux
  write, so it was not run.
- Built the injection-capable hook from mods/capture/mod.c
  (sdk/build.ps1, 198,912 B, implements b_shared / b_override /
  b_stop). Packaged as the experimental **overlay** plugin; installing it
  restarts the goggles UI.
- Documented the remaining PC-stream work: b_receiver (JPEG -> BGRA) plus a
  PC sender over the RNDIS link, since ADB is off.

## Unreleased - 1080p video out (2026-11-26)

- Found the goggles **already encoding 1920x1080 H.264 at 50 fps** (logcat:
  OMXVC8000Enc [Graph1] ... resolution:1920*1080, FPS: 50000/1000), fed by
  LCDC writeback at 60 fps. The encoded stream goes to the internal MDC channel
  zv900_app_liveview_chn.
- Raw frame mirroring (E420Z) cannot do 1080p over ADB (~6 MB/frame); the
  encoded path is ~1.5 MB/s, so 1080p30 is a plumbing problem, not a speed one.
- Inventoried the components: ideo_reader.lcdc, ideo_reader.mdc/
  .avc.mdc, ideo_encoder.avc|hevc.vc8000e, ile_writer.binary,
  container_muxer.ffmuxer, and ideo_writer.uvc (USB webcam sink).
- Documented three routes in docs/VIDEO-OUT.md. Route B (omx_recordtest)
  needs a DUML route change plus an I2C mux write, so it is not run blind.
- natartos stream is PC -> goggles, the opposite direction; its device half
  already exists here as hook_overlay.so.

## Unreleased — board/firmware naming (2026-11-26)

- Searched firmware for the board markings: **`IE1000`, `ACG2430`, `NBSK39`,
  `P44M76`, `AC00004` appear nowhere** — not in `/vendor`, `/system/etc`, the
  `dji_wlm` / `dji_sdrs_agent` / `dji_glasses` binaries, the `sparrow2` images,
  or `dmesg`.
- What *is* there: platform `dji,e3t` / "DJI e3t zv300 V3 platform"; radio
  firmware set `sparrow2` on `modem-sparrow-*` partitions; `dji_sdrs_agent`
  strings `hold/release P1/S1 reset pin` and `dji.p1.heartbeat_disable` (two
  radio dies); a Nordic **nRF52810** for the wireless-mic link.
- Documented the three ways to get video on the PC: E420Z live preview (works,
  display mirror), raw USB H.265 (blocked), OMX/LCDC tap (research).
- `SPARROW2.md` §10A extended, new §10B "Board identifiers".

## Unreleased — S2 capture measured on-device (2026-11-26)

- Ran the S2 capture path on the owner's N3 with the root shell up. **Result:
  blocked, and correctly so.**
  - Confirmed the S2 enumerates as `2ca3:1020` with interface 3 / EP `0x84`.
  - `test_wl_vdec` exists and `-d` really is "dump encoded stream", but the
    vendor's own `-t usb_vdec` example aborts with `FORTIFY: fseeko: null
    FILE*` (SIGTRAP).
  - Cause: `/system/etc/wlm_cfg.json` points `test.liveview_venc_cfg` at
    `/etc/wl_liveview_venc.json`, which does not exist. `/etc` is
    `/system/etc` on dm-verity, so it must never be created — that would be a
    `/system` write and a guaranteed brick on reboot.
  - `-p` and `-k` fail to parse on this build (`rc=255`, usage printed).
  - `test.liveview.start_cmd` / `finish_cmd` are **empty arrays**, so
    `006E0001`/`006E0000` are not configured here at all.
  - The S2 link is down: logcat `recv_cnt 0, recv_bytes 0, freq 0, bitrate 0`.
- The real readers are OMX nodes: `wlvdec` (`wl_port_id`, iface 0 EP `0x81`,
  h265 640×360) and `media_server` holding iface 3 EP `0x84` for the main
  stream. Documented in `SPARROW2.md` §10A.
- The app now returns that exact diagnosis instead of a generic failure, and
  the Sparrow2 card carries a "measured on this build" note.
- Practical route for S2 video today: the existing E420Z live preview, which
  mirrors the already-decoded goggles display.
- Device left as found: decoder killed, test logs removed, only
  `/data/local/tmp/s2cap.sh` added.

## Unreleased — S2 video capture (2026-11-26)

- New **S2 video capture** mod (`s2cap`, type `tool`, data-only): installs
  `/data/local/tmp/s2cap.sh`, the auditable helper for the vendor decoder path.
  Data-only mods now install and uninstall **without** `vendor_write` and
  without stopping the goggles UI.
- New Sparrow2 UI card: **S2 video (H.265)** with stream selector
  (main 1920×1080 / secondary 640×360 / auto), duration, Probe, Capture, Pull
  and Stop.
- New API: `s2_probe`, `s2_capture`, `s2_stop`, `s2_pull`, `s2_liveview`.
  Captures are time-boxed; `stop` only ever kills `test_wl_vdec`.
- Capture is receive-only: it dumps the encoded stream the S2 already sends
  over USB bulk endpoints and writes only `/data/local/tmp/s2cap`. Nothing is
  remuxed, re-routed or transmitted, and decoding happens on the PC.
- `-p` is optional ("Auto (no -p)") because some builds reject it.
- `record_test_script.sh` and the `006E0001`/`006E0000` link start/stop are
  documented but **not wired**: re-routing video or starting the link needs a
  bench run first. `s2_liveview()` returns a clear refusal instead of guessing
  the DUML frame.
- Docs: `SPARROW2.md` §10A (capture path, evidence, status) and
  `NATARTOS.md` (what of natartos maps to the N3, and what does not).

## Unreleased — pywebview control deck (2026-11-26)

- Replaced the CustomTkinter shell with a **pywebview (WebView2) + HTML/CSS/JS**
  desktop app: `app/webapp.py` host, `app/web/{index.html,styles.css,app.js}`.
  The Tk app stays as a fallback and `Start N3 ROOT.cmd` / `run.ps1` choose
  automatically.
- Seven pages wired to the real backend: Connection, E420Z, Sparrow2, Root
  Shell, Mods & UI, Logs, Settings. Sidebar pill, sticky header, command
  palette (Ctrl K), toasts, count-up numbers, styled risk confirmations.
- Safety is visible in the UI: every action carries SAFE / EXPERIMENTAL / RISKY,
  risky confirmations focus **Cancel**, and Settings shows the `/system` /
  dm-verity / no-unbrick warning.
- New backend methods: `live_resolutions()` (the UI no longer hardcodes scales)
  and `open_doc(path)` (read-only, `docs/` only).
- `run_shell` blocks `/system`, verity, partitions, bootloader, flashing and raw
  block writes before anything reaches the goggles.
- `status()` probes libusb and the UI process in parallel and caches for 2 s.
- `webapp.py --selftest` boots the real window and reports the rendered page,
  scale list, themes, palette and any uncaught JS error.
- `app/tools/ui_shot.ps1` captures any page headlessly at any size; screenshots
  added under `docs/screenshots/web_*.png` and `docs/screenshot.png`.
- Fixed the `E42OZ` → **E420Z** typo across the app and docs.

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
- N3 Menu input map corrected: 5-way center = `event0` 28 (select), Back =
  `event0` 158, directions = `event3` 103/108/105/106; **power has no input
  event**. Long-press 5-way up now toggles the overlay; the long-center gesture
  (which opened the stock left sidebar) was removed. The app installer now
  deploys `n3mods.so`.
- Added `docs/UI-INTERNALS.md` and ELF/EW analysis tools
  (`disasm_ui.py`, `ui_relocs.py`, `disasm_menu2.py`, `ui_actions.py`).
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

- New CustomTkinter control deck: Connection, E420Z, Root Shell, Mods & UI,
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
