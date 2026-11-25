# GFSK patch — host-tested, not deployed

`app-gfsk/` is a copy of the handoff app with a **read-only GFSK** provider
added. It is not deployed to the goggles.

## What changed

- `metrics.h` — added `gfsk`, `no_link`, `packets`, `recv` fields.
- `metrics.c` — `parse_gfsk()` parses:
  - `rf/rssi1/2[rf,rssi1,rssi2]`
  - `recv/pkt[recv,pkt]`
  - `f-m/freq/area/tx-area[fm,freq,area,tx_area]`
  - Sets `no_link` when `rssi1 >= 127`; negative RSSI values are valid.
- `linkmon.c` — GFSK branch:
  - `GFSK NO LINK  FREQ ...  PKT ...  RECV ...`
  - `GFSK RSSI ... dBm  FREQ ...  PKT ...  RECV ...`
- `bmp.c` — GFSK dashboard with `GFSK LINK - NOT IQ` and `NO LINK`.
- `gfsk_metrics.sh` — read-only provider:
  - `logcat -d -v brief | grep -a 'gfsk_agent: dev_mgr:' | tail -1`
  - `GFSK_LOG=<file>` supported for host tests.
  - Prints `NO METRICS` if no line.
- `linkmon.mod.json` — uses `/data/sdr-scanner/gfsk_metrics.sh`.
- `deploy.sh` — pushes/chmods `gfsk_metrics.sh`.
- `scanner_test.c` — tests no-link and linked GFSK lines.

## Host tests

Built with Zig `x86_64-windows-gnu`:

```
scanner tests: OK
```

Strict rebuild with `-Werror` and asserts active (`-UNDEBUG`) also passes.
An **aarch64 compile check** (`zig cc -target aarch64-linux-gnu -c`) passed
for all app sources, including `scanner_ui.c` and `scanner_test.c`. This is
only a compile check; an Android NDK/bionic link is still required for a
deployable arm64 binary.

Includes:
- WLM/LTE parser tests (existing).
- GFSK no-link: RSSI 127 → `valid`, `gfsk`, `no_link`, freq 2466, pkt 119, recv 0.
- GFSK linked: RSSI -62 → `valid`, `gfsk`, not `no_link`, freq 2437, pkt 120, recv 7.

End-to-end with the adapter:

```
--- no link ---
GFSK NO LINK  FREQ 2466 MHz  PKT 119  RECV 0

--- linked ---
GFSK RSSI -62 dBm  FREQ 2437 MHz  PKT 120  RECV 7
```

Both runs wrote:

- BMP 6,220,854 bytes
- `fb_shared` 8,294,400 bytes

## What is still missing

- No O4 SDR IQ samples.
- No LTE metrics (`rsrp/rsrq/snr/band`); LTE is powered off in `power_ctrl`.
- No `/data/dji_wlm.log`.
- No arm64 binary built here (Android NDK not installed).
- Not deployed; the natartos overlay that consumes `fb_shared` is not in the
  package.

## Safety

- Provider is `logcat` only; no DUML, no SDR/radio control, no writes to
  `/system` or `/vendor`.
- `gfsk_metrics.sh` only reads logs.
- `deploy.sh` (if ever used) writes only `/data`; owner approval is required.
- RSSI 127 is shown as `NO LINK`, never as a fake signal.
- The UI is labelled `GFSK LINK - NOT IQ`.

## In-goggles display status

The natartos `hook_overlay.so` was built and loaded, but the N3 display test
went black: the overlay scans for G3 dma-buf mappings and suppresses real
frames when no match is found. It has been removed and the stock UI restored.
See `DISPLAY-OVERLAY-N3.md`. A safer N3 copy-on-push overlay is the next
display experiment; it needs approval.

## To use on device (after approval)

1. Build arm64 with Android NDK or a suitable cross toolchain.
2. Confirm the natartos overlay that consumes `fb_shared` exists.
3. Deploy to `/data/sdr-scanner` and run:
   `scanner --link-monitor --metrics-cmd /data/sdr-scanner/gfsk_metrics.sh ...`
4. Verify `fb_shared` is exactly `8294400` bytes and `setprop ctl.start
   dji_glasses` restores the stock UI.
