# Changelog

## 1.4.1 — PC display auto-switch (2026-11-28)

- PC → Goggles page: **PC display** card with current mode, **Switch to 1080p**
  and **Restore**; **Auto 1080p** setting.
- Start saves the current PC mode and switches to 1920×1080 @ 60 Hz before
  capture; Stop restores it. Buttons disabled while live.
- Backend `pcvideo_display(switch_now, restore)` and a `display` block in
  `pcvideo_info`.
- Verified 1920×1080@60 ↔ 2048×1536@240; saved original retained.
- Unchanged 1080p60 H.264/H.265 hardware tunnel.

## 1.4.0 — PC → goggles 1080p60 hardware tunnel (2026-11-28)

- Added the working `OMX.dji.video_decoder.avc.vc8000d` hardware decoder tunnel
  into `OMX.dji.iv_renderer.yuv.extra_blending`: 60.0 fps, 30 Mbps, no copy.
- Standalone `vc8000d` free-runs; `OMX_SetupTunnel(decoder, 1, sink, 0)` is
  required. Ports: decoder in 1920×1080/16, out 1920×1080/7; sink main
  1920×1080/7 + URL, sub 640×360/7. Allocate only decoder input and sink sub.
- Hardware output is linear NV12, stride 2048, 3,317,760 B; 16 input buffers
  and a 6 MB port fixed the input stall.
- First SPS/PPS is fed as `OMX_BUFFERFLAG_CODECCONFIG`; NVENC sets `aud=1` and
  `repeat_headers=1`.
- H.265 tested on the same tunnel: `hevc.vc8000d` + `hevc_nvenc`, 20 Mbps,
  **60.1 fps**, no drops. H.264 remains the default.
- Software `avc.ffmpeg` fallback is ~40 fps and emits **I420 planar** despite
  reporting format 21; U/V are now interleaved explicitly.
- PC capture runs at native 1920×1080 (the display was switched from
  2048×1536); the sender draws the Windows cursor.
- App: new **PC → Goggles** backend/page (`pcvideo_*`), H.264/H.265 selector,
  bitrate/cursor settings, live fps/bitrate/frames/encode/device stats.
- Removed the old JPEG/`fb_receiver` PC Stream route and the obsolete
  `DisplayEngine` hook warning.
- Docs: `docs/PC-TO-GOGGLES.md` and `sdk/examples/display_sink/README.md`
  document the tunnel, the planar fallback, and the exact port setup.

## Unreleased — perma-root / ADB experiment (2026-11-27)

- Added `perma-root-exp/`: static design plus host/device scripts for a
  boot-persistent root ADB shell.
- Path: `/blackbox/system/sys_perf` filename injection ->
  `/data/dji/boot-adb.sh` -> `usb_adb.sh` -> `adbd` in `u:r:su:s0`.
- Uses `/data` and four tiny `/blackbox` filenames; **no `/system` or
  `/vendor` writes**.
- Benign hook first, kill switch (`/data/dji/perma_off`), and removal are
  documented.
- Added `BOOT-ADB.md` (exact gate + expected output) and
  `DEVICE-WIDE-ROOT.md` (capability matrix; `/system` remains read-only).
- Added `host/rootctl.py`: guarded `ls`/`cat`/`pull`/`push`/`exec` over root
  adb; `/system` and block-device writes are refused.
- Added `docs/PC-TO-GOGGLES.md`: the `extra_blending` 1080p main + 640x360 sub
  config, the `OMX_SetParameter(0x0100000D)` URL, why the earlier probe was
  black, and H.264 vs H.265.
- Added `perma-root-exp/VERITY-BYPASS-EXP.md`: why userspace root cannot
  disable dm-verity/AVB; `/system` stays read-only.
- Added `perma-root-exp/SELINUX-PERMISSIVE.md`: what permissive would unlock
  (SELinux checks only), why `su`/`dji_services` cannot `setenforce`, and why
  `/system`/verity are unaffected.
- Trimmed unsupported capture notes from `SPARROW2.md`.

## 1.3.0 — Deterministic Find N3 (2026-11-27)

- New **Connection → Find N3** action: matches `USB\VID_2CA3*` in PnP, selects
  the `MI_00` Net adapter by hardware ID, reads its IPv4 and ARP neighbours, and
  probes TCP 4444 only on that adapter. Four stages: `no_device`, `no_rndis`,
  `no_shell`, `shell_up`.
- The RNDIS/scan path no longer falls back to a non-DJI adapter. `_local_ipv4()`
  is empty when the goggles are absent, and `_sweep_rndis()` refuses instead of
  scanning a home LAN.
- `start_root()` preflight reports "no USB", "USB but no RNDIS" or "RNDIS up but
  no 4444" instead of a generic "not found".
- `goggles_adapter()` now uses `Get-NetAdapter.PnpDeviceID` (the
  `Get-NetAdapterHardwareInfo` property was empty on current Windows).
- Neighbour discovery filters broadcast/permanent/incomplete entries.
- Classic Tk log no longer prints `✔` when an action returned `False`.
- Verified on stock 0900: `no_shell`, `Ethernet 2` `192.168.60.1/24`,
  goggles `192.168.60.2`; no LAN sweep when no adapter is present.

## Unreleased — lower-latency video out + 60 Mbps research (2026-11-27)

- New **`mods/h264/enctranscode.c` / `n3enctranscode.so`**: the vc8000d
  decoder tunnelled into the second vc8000e. Fed 1080p60 NVENC noise it produced
  **26.9 MB in 3 s (~71 Mbps)** at the 60 Mbps target, proving the encoder is
  not capped at 10 Mbps; it then crashed in `processBuffer+2844`, so it is a
  proof only. The reader→encoder tunnel stays stable.
- `mods/h264/enctunnel.c` / `n3enctunnel.so`: the LCDC reader is
  tunnelled into a second `vc8000e` at a 60 Mbps port-definition target. Stable
  1920×1080 encode, no crash (manual copies crash `processBuffer`). The 60 Mbps
  target survives Idle; static UI content only needs 7–11 Mbps, so a live
  drone feed is required to measure the real ceiling. See `docs/GSTREAM.md`.
- `OMX_IndexParamVideoBitrate` is a **setConfig** index here (CBR, port 0/2);
  the vendor `duss_hal_venc_set_ratectrl` call fails with `0x80001001`, so the
  port definition remains the working bitrate path. `vencMode` 0 = storage.
- Goggles Stream now fragments the fMP4 **every frame** (`frag_every_frame`)
  instead of at keyframes, flushes each packet, uses a **512 KB** ring, sets
  **TCP_NODELAY** on both ends, and keeps the MSE playhead **0.12 s** behind the
  live edge (jump at 0.6 s). Offline: 312 frames → 312 fragments, 0 decode
  errors.
- New **`mods/h264/encprobe.c` / `n3encprobe.so`**: second vc8000e at 60 Mbps
  fed from the LCDC channel, with a synthetic-pattern mode to measure the
  encoder ceiling. 3 s / 24 MB cap, guaranteed Idle + buffer free + FreeHandle,
  one-shot marker. Not integrated into the app yet; needs an on-device run.

## 1.2.1 — RNDIS auto-recovery (2026-11-27)

- **The root-shell helper now finds the DJI network adapter itself** by USB PnP
  ID (`VID_2CA3`); it never touches Wi-Fi, VPN, Tailscale or a normal Ethernet
  adapter.
- **APIPA recovery.** If the adapter only has a `169.254.x` address (no DHCP
  lease), it renews DHCP, then temporarily adds `192.168.60.1/24`,
  `192.168.42.1/24` or `192.168.137.1/24` to that adapter and sweeps the /24 for
  port 4444. The temporary address is removed on Stop root or app exit; this
  needs administrator.
- **Full /24 sweep** for any DHCP lease, not just `.2`/`.129`.
- **Full DUML session init retry**: if the minimal handshake yields no listener,
  the RCE is retried after the DJI-Assistant-style init used for file reads.
- **Multi-`nc` payload**: `/system/xbin/busybox`, `/system/bin/busybox`, then
  `/system/bin/toybox`.
- `handshake replies: 0` is called out as a red flag in the troubleshooting
  docs. Firmware 1.09 remains untested; these are fallbacks, not a verified
  1.09 exploit.
- Goggles Stream is unchanged from 1.2.0 (1080p60, 10 Mbps confirmed).

## 1.2.0 — Goggles Stream (2026-11-27)

- **Goggles Stream page + `app/gstream.py`**: plays the goggles' own
  **1920×1080 H.264** on the PC with no re-encode, telemetry rail and
  fullscreen. Verified live in WebView2: readyState 4, buffered 1.7→11.7 s,
  718 frames, 0 dropped.
- **`mods/h264/videoout.c` / `n3videoout.so`**: reads
  `zv900_app_liveview_chn` with `OMX.dji.video_reader.avc.mdc`, prepends the real
  vc8000e SPS/PPS (`67 64 00 34 … 68 ee 3c b0`), and serves Annex-B H.264 on
  **TCP 5571**. 4 MB drop-to-newest ring; read-only consumer.
- Measured **59–60 fps**, ~2.0–2.2 Mbps on a static UI (10 Mbps pipe cap), and a
  4 s pull from the PC endpoint decoded with **0 errors**.
- `app/gstream.py`: deploy/arm, ffmpeg `-c copy` to fragmented MP4, loopback
  **HTTP 8771** + CORS, MSE playback; Start/Stop clears the vendor properties.
- **Bitrate ceiling**: `bitRate 10000000` is a literal in read-only
  `/system/etc/app_liveview_pipe.json`; never edited. The raw LCDC YUV channel
  reads at **59.3 fps** and a second vc8000e accepts **60 Mbps**, so a custom
  reader→encoder mode is the only route above 10 Mbps.
- `ui_shot.ps1` now accepts relative `-Out` paths; the page shows “—” instead of
  a fake `0 ms` latency.
- **Root shell auto-discovers the RNDIS address**: reads the Remote NDIS/USB
  adapter IPv4, probes `x.y.z.2` and `x.y.z.129` on 4444, adopts the answer, and
  keeps `N3_HOST` as an override. `is_root()` starts a throttled background
  scan, so a shell that appears after USB re-enumeration is picked up.
- App version is **1.2**.

## Unreleased - PC stream working (2026-11-26)

- **PC screen to goggles works**, verified end to end: 11.8 fps sustained at
  1280x720 with only 2 frames over budget in a 20 s run.
- Latency fixed by dropping stale frames: the receiver skips to the newest
  queued frame before decoding and caps `SO_RCVBUF` at 256 KB. `pcstream.py`
  paces to what the goggles can consume (12 fps at 720p, 5 at 1080p).
- Anti burn-in (`DuScreenSaver`) identified: a bitmap slideshow that steps
  every ~1.6 s and is dismissed by **key input, not motion**. While `fb_hold`
  exists the hook sends a BACK key every ~20 s, invisibly under the stream.
- Hook fixes: the push detour re-asserts the frame while `fb_hold` exists,
  cleanup no longer deletes `fb_shared` or kills `fb_receiver`, and a stale
  `fb_stop` is cleared at receiver startup (it silently disabled injection).
- New `app/tools/pcstream.py` sender (size/fps/quality, TCP_NODELAY, small
  SO_SNDBUF) and a rewritten `mods/stream/README.md` with the working recipe.

## Unreleased - Stage 2 groundwork: hardware H.264 (2026-11-26)

- PC side proven: h264_nvenc encodes 1080p60 at **8x realtime** (300 frames in
  5 s of content, 8 Mbps ~ 1 MB/s) on the RTX 4070 SUPER.
- New mods/h264 probe mod: loads libOmxCore.so inside dji_glasses and
  enumerates components. Works: **57 components, 5 decoders, 3 encoders**,
  including OMX.dji.video_decoder.avc.ffmpeg and the VC8000 family.
- Learned and documented the mod contract: export 
atartos_mod_init(dlsym),
  never reference dlopen directly, install 755, and write the file through the
  dji_services push path (su cannot write 
endor_file).

## Unreleased - PC screen into the goggles (2026-11-26)

- **Working:** PC desktop -> goggles over the RNDIS link. New 
b_receiver
  (aarch64, static) decodes length-prefixed JPEG into 
b_shared; the existing
  hook_overlay.so inject thread puts it on the display. Measured 11.7 fps at
  1200x900 in an 8 s test.
- Packaging: mods/stream/ (source, binary, README) and the experimental
  overlay plugin, which replaces the capture-only hook when installed.
- Found and documented the two gotchas: the receiver must run in u:r:su:s0
  (root ADB) because dji_services cannot exec /data ELF, and the file must
  stay labelled system_data_file (relabelling to shell_data_file makes it
  unreadable to su).
- Stop is clean: SIGTERM removes 
b_override, touches 
b_stop, UI repaints.

## Unreleased - recorder test + PC-stream packaging (2026-11-26)

- Bounded omx_recordtest test: init + record start succeed against the 1080p
  display channel, then a **segfault on stop/mux**; no file produced; device
  unaffected. The factory wrapper also does a DUML route change and an I2C mux
  write, so it was not run.
- Built the injection-capable hook from mods/capture/mod.c
  (sdk/build.ps1, 198,912 B, implements 
b_shared / 
b_override /
  
b_stop). Packaged as the experimental **overlay** plugin; installing it
  restarts the goggles UI.
- Documented the remaining PC-stream work: 
b_receiver (JPEG -> BGRA) plus a
  PC sender over the RNDIS link, since ADB is off.

## Unreleased - 1080p video out (2026-11-26)

- Found the goggles **already encoding 1920x1080 H.264 at 50 fps** (logcat:
  OMXVC8000Enc [Graph1] ... resolution:1920*1080, FPS: 50000/1000), fed by
  LCDC writeback at 60 fps. The encoded stream goes to the internal MDC channel
  zv900_app_liveview_chn.
- Raw frame mirroring (E420Z) cannot do 1080p over ADB (~6 MB/frame); the
  encoded path is ~1.5 MB/s, so 1080p30 is a plumbing problem, not a speed one.
- Inventoried the components: 
ideo_reader.lcdc, 
ideo_reader.mdc/
  .avc.mdc, 
ideo_encoder.avc|hevc.vc8000e, 
ile_writer.binary,
  container_muxer.ffmuxer, and 
ideo_writer.uvc (USB webcam sink).
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

## Unreleased — S2 capture notes (2026-11-26)

- The vendor encoded-capture path was investigated and is **not enabled**.
  It requires a `/system` config or a flash dump, both outside the safety
  rules. Use the E420Z display mirror or Goggles Stream.

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
