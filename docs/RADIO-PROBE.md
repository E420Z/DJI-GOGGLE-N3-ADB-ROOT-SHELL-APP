# N3 radio/video probe — can we sample the internal 5.8 GHz?

Date: 2026-11-25. Owner's device. **Read-only**: `ls`, `cat`, `getprop`, `dmesg`,
`logcat`, `find`, `grep`, plus a few DUSS *query* attempts (no writes, no factory
mode, no service stops, no modem/firmware changes).

Evidence: `device-evidence/2026-11-25_19-42-02/`

## Naming (important)

- **Sparrow2** = DJI's internal 5.8 GHz SDR/modem chip used by the goggles
  (available as O4 / O4+). Its USB **product string is `C5`** and its USB ID is
  `2ca3:1020`. When this document says "C5" in the USB/descriptor sense it means
  that device, not Espressif.
- **ESP32-C5** = an Espressif Wi-Fi/Bluetooth SoC, completely unrelated. The
  C5VRX analog-video project uses an **ESP32-C5**, not DJI's Sparrow2.
- Sparrow2 is a full radio SoC: separate **AP / CP / DSP / L1C / SCP** images plus
  RF NVRAM and AMT (see inventory below). IQ samples necessarily exist *inside*
  it; the question is whether any AP-side interface can request/stream them.

## Short answer

- The internal 5.8 GHz path is the **Sparrow2** modem (USB product string `C5`,
  `2ca3:1020`), the same family as Goggles 3. The AP can reset/flash it but
  **cannot read its memory or IQ**. There is no `/dev` IQ/ADC/FFT interface.
- There **is** a shipped Sparrow2 text console, `/system/bin/sdr_shell`, and a
  full factory test suite (`test_sparrow2_*.sh`, `test_rf.sh`, …). This is the
  closest analogue to the ESP32-C5 `MODEM_DIAG` lead. However it is not an
  on-device API: the `test:7` DUSS host is the **factory PC fixture**. A
  factory-flag + `dji_amt` restart did **not** register it, and all queries
  returned `-1007`. See the console section below.
- The N3 **does** have a real **display video path**: `/proc/display/testcmd`,
  a **video plane 4 (NV12)**, gfx planes 5/6, a writeback plane 7, `test_disp`,
  `/data/disp_fifo`, `/dev/dji_video_in`, `/dev/dji_vtx`, and hardware
  H.264/H.265/JPEG encoders. It is a display/video path only — not an RF
  sampler.

## Radio evidence

```
USB device:          2-1 2ca3:1020 C5
Processes:           dji_sdrs_agent, dji_wlm, dji_gfsk_agent, dji_media_server
Kernel modules:      spi_slave_nrf52810_rx, spi_nrf52810_rx
SPI:                 spi1.0  spi:wl-nrf52810-master
Modem firmware:      /vendor/modem_firmware/sparrow2/{cp,ap,dsp,l1c,scp}.img + nvram
Boot:                fastboot flashes modem-sparrow-* partitions every boot
```

- `dji.json` has `sdrs_agent_service…sdrs_log.channel.sdr_dump` = **status 0**,
  dev `/bulk/s2_sdrdump`, output `dump_store`. That is a modem **RAM/core dump**
  channel, not an IQ stream. G3 research shows it is event-triggered and not
  requestable with known tooling.
- Logs show `handleSDRRole`, `sdr_bw_ifram_recv`, `sdr_ext_info`,
  `sdr_link_info_recv`, `sdr_link_test_recv` — link control/metrics, not samples.
- `gfsk_agent` prints RSSI/packet counters only.
- No RF IIO device: `/sys/bus/iio/devices` is empty; `/proc/misc` contains video
  codecs, not an SDR/ADC.
- The C5 images are `TBIE`/`PRAK` encrypted; the AP has no plaintext and no
  readback. G3’s `MODEM_LOAD_CHAIN.md` documents the same chain.

**Conclusion:** no simple internal IQ/analog sample path. Enabling `sdr_dump`,
flashing modem images, or touching OTP is not a route to IQ and is high risk.

## Display/video evidence

```
/proc/display/plane:
  plane 4 - video: user disabled, no input frame
  plane 5 - gfx0: 1920x1080 argb8888 (dji_glasses)
  plane 6 - gfx1: 1920x1080 argb8888 (CompositorPrivT)
  plane 7 - wrb : 1920x1080 rgb888-i32 (media server / writeback)

/proc/display/testcmd: dumpregs, dumpframe, setparam, print
/dev/dji_display, /dev/dji_video_in, /dev/dji_vtx, /dev/dji_disp_consumer
/system/bin/test_disp, test_disp_init.sh
  test_disp_init.sh: /system/bin/test_disp -p 3 < /data/disp_fifo &
  test_disp usage strings: pixfmt, fps, reserved_lines, plane_id, frame_file_path
Media service: liveview + local/remote playback supported;
  hdmi_dp_in=false, uvc_only=false, simulator=false
```

- The display is MIPI-DSI 1920x1080@60; VOP0 planes are video/NV12, gfx0/gfx1
  ARGB, and a writeback plane.
- `test_disp` can display frames from a FIFO (`/data/disp_fifo`), and there are
  hardware H.264/H.265/JPEG encoders/decoders (`codec_h264e_e3t`,
  `codec_h265e_e3t`, `vc_encoder_pm_jpeg`, `vc_decoder`).
- `dji_video_in` is a platform driver (`video_in_probe success`); likely the
  decoded-video input path, not an RF sampler.

## Deep check of the C5 (Sparrow2) USB interfaces

- The C5 exposes **11 vendor interfaces**, all `class ff / subclass 43 / proto 01`,
  two endpoints each. Only `2-1:1.4` is bound to `usbfs`; no interface is a
  standard SDR/ADC/IQ device.
- `sdrs_agent_service…sdr_dump` is `status 0`, output `dump_store`.
  `dji_bb_dls.json` shows the stores are **AP/CP/L1C/DSP crash dumps**
  (`ap_crash_store`, `cp_crash_store`, `l1c_crash_store`, `dsp_crash_store`),
  not sample streams.
- `wlm_cfg.json` has link/video keys (`support_dual_chnl_video`,
  `video_4d_slice_hdr`, `video_5d_slice_hdr`) — digital link configuration, no
  analog/FM/IQ mode. The `sdr` keys there mean the **digital link**, not IQ:
  `sdr_agent_host_id 0x0e00`, `sdrs_agent_host_id 0x0e04`,
  `sdr_threshold_kbps 4000`, `sdr_rpt_tunnel_map`, and `SDR_ONLY` /
  `HYBRID_LTE_SDR` link modes. They are throughput/tunnel settings.
- `gfsk_agent_cfg.json` has a `gfsk_crash_dump` channel only.
- The SDRUART log is pairing/role/link control (`cp_role`, `sdr state`,
  `pair cmd`), not samples.
- No `analog`, `FM`, `demod`, `tuner`, `IQ`, `ADC`, `FFT`, or `spectrum` mode
  was found in the readable configs. The Sparrow2 **firmware images are
  encrypted**; the user-space tools (`dji_sdrs_agent`, `dji_wlm`) are readable
  but only expose link/log/dump handling, not an IQ API.
- `/dev/dji_video_in` is attached via `duss_hal_attach_video_in` — a **video
  frame input**, not an RF sampler.

**Conclusion (updated):** there is no exposed analog/IQ path from the built-in
Sparrow2 modem. No on-goggles sampling/console path has been found. The display
path is a display/video path only; it does not sample the O4/Sparrow2 modem.

## Factory/test surface (also checked)

- `amt_test_cmd` (8 KB), `dji_engpc` (137 KB), `dji_mb_ctrl` (18 KB), and
  `dji_sdrs_agent` (385 KB) are readable binaries. None contains a usable
  `IQ`, `ADC`, `spectrum`, or `demod` **API**; `dji_sdrs_agent` does contain the
  dump/log strings (`dump_v0`, `dump_v1`, `sdrs_dump_channel_*`).
- `/system/bin/sdr_shell` + `test_sparrow2_*.sh` are the real Sparrow2
  test/console surface (details above). They expose link, board-ID, time-sync,
  GPIO, and an ASCII console channel — not a documented IQ command.
- `/system/bin/dji_mb_ctrl_safe.sh` is an **aging-test lock wrapper** around
  `dji_mb_ctrl`, not an RF mode.
- `/system/etc/dji_autotest/` exists, but has no analog/RF/SDR hits.
- `dji_wlm` readable strings are trace/link (`sdr_enable`, `lte_enable`,
  `test_air_send`), not sample capture.
- SDRUART is pairing/role/link control; `dji_bb_dls.json` stores are crash dumps.
- Public G3 sources also state G3/N3 only support the O4 digital link; analog
  needs an added receiver/module (or a Cosmostreamer-style external box).

## What is *not* present

- No HDMI/DP input (`hdmi_dp_in=false`).
- No UVC input; `uvc_only=false` (and G3’s UVC gadget sends no frames without
  a media-server work-mode switch).
- No `simulator` mode enabled.
- No LTE USB device/`wwan` class on this unit; `lte_service` config exists but
  no LTE hardware was found.

## Safe next steps

1. **Factory-mode console — attempted, on-device path exhausted.** Creating
   `in_factory` and restarting `dji_amt` did **not** register `test:7`; every
   query stayed at `-1007`. The remaining route is the **PC↔AMT/gadget
   protocol**, which is manufacturing/calibration/file/auth (including OTP file
   receive and secure-debug auth) and is **not IQ**. Not recommended.
2. **In-process DUSS client / host registration** (hooking): code inside an
   already-registered DJI process could use the `0x55` channel or bind the
   `test:7` host. Non-read-only, high effort, and still no evidence of an IQ
   command. Only worth revisiting if a command table surfaces.
3. **Alternate on-device surfaces** (static/read-only): `/bulk/s2_remotefile`,
   `/bulk/s2_da`, and the AMT/USB gadget protocol are the remaining
   AP↔Sparrow2 channels. They are logs/file/auth, not IQ, but they are the only
   on-goggles software left to inspect.
4. **Do not** enable `sdr_dump`, flash modem images, or touch OTP/keys/AMT
   secure-debug chasing IQ. The AP has no readback and the images are
   encrypted.

**Recommended order:** the on-device console theory has been tested and closed.
The only remaining on-goggles software leads are the bulk/AMT channels; treat
them as read-only research, not an IQ claim.

## AP ↔ Sparrow2 control path (DUSS) — checked

- `dji_sdrs_agent` opens `/dev/ttyS1`, the `/bulk/s2_da` channel, the modem
  reset GPIO, `/data/dji_sdrs_agent_pm_*`, and a DUSS socket.
- The AP has a **DUSS message bus**: `/dev/socket`-style endpoints
  `@/duss/mb/0x1c01…0x1f00`, and `dji_mb_ctrl` can send arbitrary messages
  (`-m target_machine -g target_type -t target_idx -s cmd_set -c cmd_id …`).
- `/system/etc/commands.json` lists command IDs for:
  `camera, fc, gimbal, rc, hdvt, vision, djiflight, bvision, ads_b, hms,
  simulator, remote_battery, ui, dm368, special, thirdflight, common, glass,
  extend, wlm, lte, smart_func`.
  **There is no `sdrs_agent`/SDR/IQ/analog command set.**
- `amt_test_cmd` only supports `rpmb_rw <iter>` (RPMB test; dangerous, not RF).
- `dji_engpc` is an LTE/WCN engineering bridge, not a Sparrow2 API (see below).
- `/dev/ttyS1` is the Sparrow2 log UART. A **text console** does exist, but it is
  driven over DUSS (`sdr_shell`), not as a login prompt on ttyS1. No
  "help"/prompt text appears in the SDRUART logs.

**Conclusion:** the AP can talk to the modem/service layer over DUSS, and a
Sparrow2 console command channel (`cmdset 9 / cmd 0x55`) is present. It is only
usable when the factory/test host is registered. There is still **no known
documented command for IQ/analog capture**. We did not fuzz `cmd_set`/`cmd_id`.

## Sparrow2 console (`sdr_shell`) and factory test suite

This is the most important new finding. The device ships tools whose entire job
is to talk to Sparrow2.

### `/system/bin/sdr_shell`

```sh
alias v1_sender="dji_mb_ctrl -S test -R diag"
sdr_shell() {
    host=14                              # "peer" switches to host 9
    [ "$1" = "peer" ] && { host=9; shift; }
    data=`echo "$@\r" | xxd -p`
    v1_sender -g $host -t 0 -s 0x9 -c 0x55 00640018$data
    # prints the bytes after "Resp message" as text
}
```

So Sparrow2 exposes an **ASCII command line** over DUSS:
`host 14 (or 9)`, `cmd_set 9`, `cmd_id 0x55`, payload prefix `00 64 00 18`,
then the command string + `\r`. This is structurally the same idea as C5VRX's
undocumented `MODEM_DIAG` path: a vendor debug channel, not a public API.

### Factory test scripts that drive Sparrow2

`/system/bin/` contains:

```
test_sparrow2_link.sh      # USB0 / UART1 / UART4 / hw-ver / heat-chase I/O
test_sparrow2_tsync.sh     # time-sync GPIO + GNSS counter, from SDRUART log
test_sparrow2_hw_ver.sh    # board id via -c 0x2c
test_reset_s2_link.sh      # toggles GPIO0 to reset S2, then re-checks link
test_sdrlog_e3t_uart5_link.sh  # ttyS1<->ttyS2 921600 loopback
pro_sparrow2_0.sh / get_upload_sparrow2_0.sh / burn_otp_sparrow2_0.sh
test_rf.sh                 # S2 CP-state aging test (reads SDRUART log)
```

Examples of the actual Sparrow2 protocol from those scripts:

```
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 0 -c 0x01                # version/link
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 0 -c 0x2c 544D190500000000  # board id
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 9 -c 0x55 00640005 ...     # shell/cmd
dji_mb_ctrl -S test -R diag -g 14 -t 0 -q 1 -s 7 -c 0xad -2 0009     # UART4
```

`test_rf.sh` is **not** a spectrum/IQ test — it only checks the CP state counter
in the SDRUART log for aging. The `*_link` scripts check connectivity, board ID,
time sync, and GPIO, not samples.

### Firmware inventory (encrypted)

`/vendor/modem_firmware/sparrow2/`:

```
ap.img  cp.img  dsp.img  l1c.img  scp.img  pwr.bin  ipc.bin
bootarea.img  amt.bin  cp_nvram.bin  rf_nvram.bin  share_info.bin
variants: wa020  wa520  wa521  wa530  za530_lite  za530_pro
```

`strings` on these images returns only random fragments — they are encrypted /
signed. So the console's command table cannot be recovered statically without
breaking the vendor's protection, which we will not do.

### Why `sdr_shell` currently returns "no response"

We tried the shipped console and simple queries (`help`, `?`, empty) and traced
the failure:

```
Send message, from machine 0x900 host 1e07, to machine 0 host 0e00,
msg_id: 00090055 ...
duss_event_send_sync_v2() error: -1002   (no machine route)
```

- `dji.json` `platform.machine_id` = **2304 = 0x900** (the goggles' own machine).
- `test.mb_route_table["diag"]` is host **`1e07`**; key `"e0"` (target type 14,
  index 0) routes to `vt_gnd → glass:1`, i.e. host **`0e00`**.
- Device logs map **`-1002` to a DUSS router error ("Router error -1002 on
  host …")**, i.e. the source/target machine pair is not routable.
- Passing `-m 2304` (same machine), or selecting `sdrs_agent_service` /
  `wl_manager_service` / `system_service`, changes the error to **`-1007`**
  (sync send rejected). Even the `cmdset 9 / cmd 0x43` ping that `dji_glasses`
  sends successfully every 500 ms fails from our transient shell.

So the blocker is **host registration**, not the command text. A socket audit
(`/proc/net/unix`) shows the local DUSS hosts that exist in normal mode:
`0x1c00`, `0x1c01`, `0x1c02`, `0x1c04`–`0x1c07`, `0x1d02`, `0x1f00`,
`0x0e03/0x0e04/0x0e07`, `0x1704`, `0x0500`, `0x0`.
There is **no `@/duss/mb/0x1e07`**. `dji_amt` is `0x1c02` and `dji_sys` is
`0x1c01`. The `test:7` host is the **factory PC fixture**, not an on-device
service. `sdr_shell` is therefore a PC-factory tool that happens to ship in
`/system/bin`.

### Factory-mode attempt (2026-11-25)

With owner approval we tried the least-persistent path and fully recovered:

1. snapshot: `us.db` md5 `386db554…`, UI stock, USB normal.
2. create `/data/dji/cfg/in_factory`.
3. restart `dji_amt` (`setprop dji.amt_service 0`, then `1`; PID 929→7355).
4. run `sdr_shell help`, `?`, `version`, `info`, `peer help`, plus a raw `0x55`.

Result: **no factory log, no `0x1e07` host, every query still `-1007`**. The
file alone does not register the PC test host; the real entry is the PC AMT
request (`factory_debug: get request from PC, cmd is [%s]`).

Recovery: removed `in_factory`, restarted `dji_amt` (PID 7556), UI stock,
`us.db` md5 unchanged, USB `rndis,mass_storage,bulk,acm`. No calibration,
OTP/RPMB, secure-debug, or firmware operation was performed.

### What this means for IQ

- A Sparrow2 console exists, but it is **PC-fixture-hosted**, not an on-device
  API. Reaching it means implementing the PC↔AMT/gadget protocol.
- The AMT command surface is manufacturing/calibration/file/auth, not IQ
  (see the AMT section below).
- The AP-side Sparrow2 channels are logs/dumps only (see channel inventory).
- IQ/samples exist inside Sparrow2's DSP/L1C, but **no exposed AP path** was
  found. The C5VRX analogy does not map cleanly: ESP32-C5 has a ROM
  `MODEM_DIAG` path; Sparrow2's firmware is encrypted and its debug console is
  host-gated.

## Sparrow2 channel inventory (from `dji.json`)

`sdrs_agent_service.configuration.sdrs_log.channel`:

| channel | transport | endpoint | purpose |
|---|---|---|---|
| `uart_log_in` | `/dev/ttyS1` 921600 | — | Sparrow2 UART log |
| `uart_log_store` | dls | — | log store |
| `modem_da_log` | bulk_single | `/bulk/s2_da`, iface 7, ep 88/08 | DA/modem log |
| `da_log_out` | socket | → `modem_da_log` | socket feed |
| `sdr_dump` | bulk_single | `/bulk/s2_sdrdump`, iface 6, ep 87/07 | crash/RAM dump (status 0) |
| `dump_store` | dump_v1 | — | dump sink |
| `ap/cp/l1c/dsp_crash_store` | dls | — | crash stores (status 0) |

Other HAL bulk devices: `/bulk/s2`, `/bulk/e3t_sys-s2_hs`,
`/bulk/s2_remotefile`, `/bulk/pc`. **None is an IQ/ADC/FFT channel.** The
`modem_da_log` and `sdr_dump` endpoints are logs/dumps, and `sdr_dump` is
disabled.

Firmware boot inventory (`sdrs_agent_service.configuration.bootctrl.image`):
`bootarea`, `scp`, `share_info`, `amt`, `pwr`, `cp_nvram`, `rf_nvram`, `ipc`,
`dsp`, `l1c`, `cp`, `ap` — flashed to `modem-sparrow-*` partitions every boot.
The user-space images are encrypted/signed, so no static command table is
recoverable without breaking vendor protection.

## AMT is manufacturing/calibration/file/auth, not IQ

`dji_amt` is the AMT service (DUSS host `glass:2` = `0x1c02`). Its PC-facing
commands, from readable strings, are:

- `sys_amt_get_serial_number` / `sys_amt_set_serial_number`
- `sys_amt_task_get_log`, `sys_amt_task_get_result`
- `sys_amt_file_recv_req_proc`, `sys_amt_file_send_proc` (file transfer with
  CRC32, including OTP file receive)
- `sys_amt_audio_factory_test` (speaker CALIB / Play / Stop)
- `sys_amt_task_check_securedebug_auth`, `sec_cmd_act_send_onetime_auth`,
  `sec_cmd_verify_onetime_msg`, nonce / onetime auth
- `start_factory`, `start_factory_oneshot`, `stop_factory`,
  `set_ssd_from_factory`, `reset_ssd_from_factory`
- `sys_amt_task_generate_auth_msg`, `dji_command_security_module_general`

There is **no** `iq`, `sample`, `adc`, `spectrum`, `rf_read`, or `dump_iq`
command. The protocol also includes OTP/file writes and secure-debug auth,
which we will not exercise. So the AMT/PC route is not an IQ path and carries
real security risk.

## `dji_engpc` is LTE/WCN engineering, not Sparrow2

`/vendor/etc/engpc/` is a generic Unisoc/Spreadtrum-style engineering bridge:

```
dev/cp.conf  : COM_DIAG -> /dev/sdiag_lte,  COM_AT -> /dev/stty_lte31,
               COM_LOG -> /dev/slog_lte
dev/wcn.conf : COM_AT -> wcnd, COM_DIAG -> /dev/slog_wcn0
dev/pc.conf  : cali bootmode exposes COM_CP_DIAG as vser /dev/ttyGS0
chnl/autotest.conf : PC-CP-DIAG  PC COM_CP_DIAG -> CP COM_DIAG  ("bbat mode")
```

This is the **cellular CP (LTE) DIAG + Wi-Fi/BT (WCN) AT** bridge. The N3 has
no LTE device, and none of these paths touch Sparrow2. `/dev/ttyGS*` is the
USB gadget serial (`g_serial`); no such node is created in normal mode.

An earlier `dji_engpc -h` probe left a short-lived `dji_engpc` process; it exited
on its own. There is **no init service** for it. Device state afterwards was
confirmed normal: stock UI running (`stock=True, patched=False`), USB config
`rndis,mass_storage,bulk,acm`, no ttyGS/ttyACM nodes.

## Wi-Fi/BT radio (the other 5 GHz candidate)

- The SoC has SDIO controllers (`f9304000.dwsd0`, `f9300000.dwmmc0`) and
  Wi-Fi/BT board configs (`wifi_board_*.ini`, `bt_configure_*.ini`), plus
  `dji_wifi_cli`.
- But there is **no `wlan0`, no `ieee80211`, no `cfg80211`/`mac80211`, no SDIO
  or PCI device enumerated**, and no wireless debugfs. Wi-Fi is not active in
  this state.
- `dji_wifi_cli` is a station scan/connect CLI, not an SDR/IQ tool.
- So the built-in Wi-Fi/BT path is not an accessible raw-IQ receiver either.

## Memory / RAM / AMT keys — checked

- `/dev/mem` exists, root-only (`crw-------`), and SELinux is enforcing.
  `/dev/kmem`, `/dev/port`, and `/proc/kcore` are absent.
- `/dev/mem` maps **AP DRAM** (`System RAM 0x00000000-0x3b9fffff`), not the C5
  modem’s RAM. The C5 is a separate USB modem; its RAM is not in the AP physical
  map.
- The only AP-visible modem memory path is `s2_sdrdump` — a **crash/RAM dump**
  channel (`AP/CP/L1C/DSP_crash.bin`), off by default and event-triggered. It is
  not a live IQ/sample stream.
- `dji_amt` config is **modem calibration/NVRAM**:
  `modem-pub_key` + `/cali/sdr/nvram/amt.bin` (vendor/original/backup).
  It is the PRAK public key and RF calibration, not an IQ or analog key.
- `dji_amt` strings contain only normal libc/pthread symbols; no key material is
  exposed in the binary.

Reading AP RAM or extracting/using AMT keys would not produce C5 IQ, and
extracting/bypassing keys is a security bypass we will not do.

## Hidden factory surface: MA Channel / AMT

- C5 interface **3** is named **“MA Channel”** (bulk ep `04` out / `84` in,
  1024-byte MPS) and is **unclaimed** (`Driver=none`).
- `dji_sys` holds **three** `/dev/bus/usb/002/002` fds; `dji_amt` is a DUSS
  service (`amt_get_nonce`, `amt_get_sn_from_cmdline`, `duss_event_*`), i.e.
  **nonce/serial manufacturing auth**, not an RF sample API.
- `dji.json` has `start_factory` / `stop_factory` events (`system_service`,
  action `P3`, `lpc_client 0x1C07`) and `amt_service` routes to
  `test`, `vt_gnd`, `ve_gnd`; `test`/`diag` routes exist.
- No `IQ`, `ADC`, `spectrum`, `analog`, or `demod` command names appear in the
  AMT/test/MA configuration. MA is manufacturing/measurement/calibration.

Using MA Channel would require the factory/AMT USB protocol (or triggering
`start_factory` and capturing DUSS), which is undocumented and risky. It is not
a documented IQ source. We have not triggered factory mode or fuzzed MA.

## Exhaustive process/FD audit

Only **one** process has a direct path to the C5:

- `dji_sdrs_agent`: `/dev/bus/usb/002/002` (the C5), `/dev/ttyS1` (modem UART),
  modem reset GPIO, DUSS socket, `/data/dji_sdrs_agent_pm_*`, and
  `libdji_crypto_lib.so` (firmware verification). It uses `usbpri_host_*` /
  `duss_hal_bulk_*`.

Everything else is not the C5 IQ path:

- `dji_wlm`: `/dev/usb-ffs/bulk4/ep1` + `ep2` (PC-facing USB gadget), `/dev/ttyS4`,
  DUSS socket.
- `usb_bulk_raw 1/4/5/6`: PC-facing gadget endpoints (`/dev/usb-ffs/bulk*`).
- `dji_hardlink_drv`: **camera/display** pipeline components
  (`mctf2`, `vtx`, `gdc2`, `ycc`), not the modem.
- `dji_arhome`: `/dev/dji_display` (compositor).
- `dji_mb_ctrl`: generic DUSS message sender; `commands.json` has no
  `sdrs_agent`/SDR/IQ command.
- `amt_test_cmd`: only `rpmb_rw` (RPMB test).
- `dji_engpc`: modem log/boot-mode tooling (not running by default).

No other process holds the C5 USB device or modem UART. The theoretical
alternative — opening `/dev/bus/usb/002/002` and claiming an unbound C5 vendor
interface — has no IQ channel/protocol and could disrupt the modem; not a safe
test.

## C5VRX / “C5” name collision

`Twotoz/C5VRX` is an **ESP32-C5** project, not a DJI C5 modem project:

- Hardware: Seeed Studio XIAO **ESP32-C5** + 6-bit resistor DAC.
- It uses the ESP32-C5’s **own Wi-Fi/5 GHz radio** to take IQ samples and
  demodulate analog 5.8 GHz FPV video to **CVBS PAL/NTSC**.
- It is a tiny receiver board that can be installed **inside** goggles
  (the README shows it in a Fat Shark module bay).

The DJI goggles’ “C5” is a **Sparrow2 modem** (`2ca3:1020`) with encrypted
firmware and no AP readback. The two “C5” names are unrelated.

**Therefore:** the C5VRX trick does not map to Sparrow2 as-is. Its enabler is a
reachable PHY debug path; Sparrow2's equivalent is encrypted and/or
factory-hosted. No on-goggles IQ/sample door was found.

Stock N3 evidence: no Espressif USB/SPI device and no CVBS/PAL/NTSC/TVP/ADV7
decoder in I²C/V4L2. `/dev/dji_video_in` is a DUSS video-frame input, not an RF
sampler.
