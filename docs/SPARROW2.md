# Sparrow2 — DJI Goggles N3 internal 5.8 GHz radio

Status: **research complete for the on-device software surface.** No exposed
IQ / ADC / raw-sample API was found. This document records exactly what was
tested, what was ruled out, and what remains (hardware / PC-fixture routes).

Date: 2026-11-25. Owner's device. Bench-only, receive-only research.

> **Safety:** no `/system` writes, no dm-verity/partition changes, no OTP/RPMB/
> fuse/bootloader/SPI writes, no firmware decryption or key extraction. The one
> factory-mode attempt below only created a userdata flag and was fully
> reverted. No calibration, OTP, or secure-debug operation was performed.

---

## 1. Naming

| Name | What it is |
|---|---|
| **Sparrow2** | DJI's internal 5.8 GHz SDR/modem SoC (O4 / O4+ link). USB **product string `C5`**, USB ID `2ca3:1020`. |
| **ESP32-C5** | Espressif Wi-Fi/BT SoC used by the C5VRX analog-video project. Unrelated to DJI. |

The USB descriptor says `C5`, which is why earlier notes said "C5 modem". In
this repo, **Sparrow2** is the correct name for DJI's radio.

---

## 2. What Sparrow2 is

`/vendor/modem_firmware/sparrow2/` contains a full radio-SoC firmware set:

```
ap.img  cp.img  dsp.img  l1c.img  scp.img  pwr.bin  ipc.bin
bootarea.img  amt.bin  cp_nvram.bin  rf_nvram.bin  share_info.bin
variants: wa020  wa520  wa521  wa530  za530_lite  za530_pro
```

Boot sequence (from `sdrs_agent_service.configuration.bootctrl.image`) flashes
`modem-sparrow-*` partitions every boot:

```
bootarea -> scp -> share_info -> amt -> pwr -> cp_nvram -> rf_nvram
         -> ipc -> dsp -> l1c -> cp -> ap
```

So Sparrow2 has an application CPU, comms CPU, DSP, L1C PHY, and sensor CPU.
**IQ samples necessarily exist inside it.** The question is whether the AP can
request/stream them. The images are encrypted/signed; `strings` yields only
random fragments, so the command table cannot be recovered statically without
breaking vendor protection.

---

## 3. Shipped debug console: `/system/bin/sdr_shell`

This is the closest DJI analogue to the C5VRX `MODEM_DIAG` discovery — a vendor
ASCII console shipped on the device.

```sh
alias v1_sender="dji_mb_ctrl -S test -R diag"
sdr_shell() {
    host=14                      # "peer" switches to host 9
    [ "$1" = "peer" ] && { host=9; shift; }
    data=`echo "$@\r" | xxd -p`
    v1_sender -g $host -t 0 -s 0x9 -c 0x55 00640018$data
    # prints the bytes after "Resp message" as text
}
```

Protocol shape:

```
DUSS:  host 14 (or 9), cmd_set 9, cmd_id 0x55
payload prefix: 00 64 00 18
then: ASCII command + "\r"
```

`/system/etc/commands.json` lists `0x55` under the **`hdvt`** command set
(`req: yes`, `ack: null`, `flags: zero`). So the console is an HDVT (digital
video link) debug command, not a documented RF/IQ command set.

No console help/prompt text appears in the SDRUART logs, so the command
vocabulary is not discoverable without a working console session.

---

## 4. Factory test scripts

`/system/bin/` ships a full Sparrow2 test suite:

```
test_sparrow2_link.sh          USB0 / UART1 / UART4 / hw-ver / heat-chase I/O
test_sparrow2_tsync.sh         time-sync GPIO + GNSS counter (reads SDRUART)
test_sparrow2_hw_ver.sh        board id via -c 0x2c
test_reset_s2_link.sh          toggles GPIO0 to reset S2, re-checks link
test_sdrlog_e3t_uart5_link.sh  ttyS1 <-> ttyS2 921600 loopback
test_rf.sh                     S2 CP-state aging check (not a spectrum test)
pro_sparrow2_0.sh              production/fastboot flow
get_upload_sparrow2_0.sh       firmware upload flow
burn_otp_sparrow2_0.sh         OTP burn flow (never run)
```

Actual protocol examples:

```
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 0 -c 0x01                 # version/link
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 0 -c 0x2c 544D190500000000 # board id
dji_mb_ctrl -S test -R diag -g 14 -t 0 -s 9 -c 0x55 00640005 ...    # console
dji_mb_ctrl -S test -R diag -g 14 -t 0 -q 1 -s 7 -c 0xad -2 0009    # UART4
```

None of these is a spectrum/IQ test. `test_rf.sh` only checks the CP-state
counter for aging.

---

## 5. DUSS routing — why the console fails on-device

```
dji.json platform.machine_id = 2304 = 0x900   (the goggles)
```

Route keys are `<hex target_type><hex target_index>`:

- `test.mb_route_table["diag"]` is host **`1e07`** (target type 30, index 7).
- Key `"e0"` (type 14, index 0) → `vt_gnd → glass:1` = host **`0e00`**.

A normal on-device query produces:

```
Send message, from machine 0x900 host 1e07, to machine 0x2304 host 0e00,
msg_id: 00090055 ...
duss_event_send_sync_v2() error: -1002   # router: no route
```

- `-1002` = DUSS router error (confirmed in device logs: "Router error -1002").
- Passing `-m 2304`, or using `sdrs_agent_service` / `wl_manager_service` /
  `system_service`, changes it to **`-1007`** (sync send rejected).
- Even `cmdset 9 / cmd 0x43` — a ping `dji_glasses` sends successfully every
  500 ms — fails from a transient shell.

A `/proc/net/unix` socket audit shows the live DUSS hosts:

```
0x1c00 0x1c01 0x1c02 0x1c04 0x1c05 0x1c06 0x1c07
0x1d02 0x1f00 0x0e03 0x0e04 0x0e07 0x1704 0x0500 0x0
```

There is **no `@/duss/mb/0x1e07`**. `dji_amt` is `0x1c02`; `dji_sys` is
`0x1c01`. The `test:7` host is the **factory PC fixture**, not an on-device
service. `sdr_shell` is a PC-factory tool that happens to be installed in
`/system/bin`.

### Prepared on-device bypass: custom `-J` bulk route

The route table also contains a **disabled** bulk route to the real Sparrow2:

```
system_service / system / e0:
  status: 0, channel: bulk, protocol: v1,
  bulk: /bulk/s2, interface 4, ep_in 0x85, ep_out 0x05,
        vid 0x2CA3, pid 0x1020
```

`test / diag / e0` is `status: 1` but `channel: local` → `glass:1` (the factory
handler). That is why the shipped console is local-only.

`dji_mb_ctrl -J <json>` can load a custom route table. The prepared probe
`app/tools/probe_n3_bulk_console.py` adds a service `sparrow_probe` with a free
source host (`test:9` = `0x1e09`) and an **enabled** bulk `e0` route over
`/bulk/s2`, then sends the same `0x55` payload:

```
py -3.12 app/tools/probe_n3_bulk_console.py --dry-run
py -3.12 app/tools/probe_n3_bulk_console.py --live --command help
```

It sends only a read-only `help` query. No factory mode, no writes. It may fail
if interface 4 is claimed by `dji_sdrs_agent` or the router rejects the free
host; variants are
`--host-name test|system|sdrs_agent --host-index 0/1/7/8/9`. This is the
remaining on-goggles software experiment.

---

## 6. Factory-mode attempt and recovery

With owner approval, the least-persistent path was tried:

1. snapshot: `us.db` md5 `386db554…`, UI stock, USB `rndis,mass_storage,bulk,acm`.
2. create `/data/dji/cfg/in_factory`.
3. restart `dji_amt` (`setprop dji.amt_service 0`, then `1`; PID 929 → 7355).
4. run `sdr_shell help`, `?`, `version`, `info`, `peer help`, plus raw `0x55`.

Result: **no factory log, no `0x1e07` host, every query still `-1007`.** The
flag alone does not register the PC test host. The real entry is the PC AMT
request (`factory_debug: get request from PC, cmd is [%s]`).

Recovery:

- removed `in_factory`;
- restarted `dji_amt` (PID 7556);
- UI stock (`stock=True, patched=False`);
- `us.db` md5 unchanged (`386db554c78e047335680dd7cdc29ee9`);
- USB back to `rndis,mass_storage,bulk,acm`.

No calibration, OTP/RPMB, secure-debug, or firmware operation was performed.

---

## 7. Sparrow2 channel inventory

From `sdrs_agent_service.configuration.sdrs_log.channel`:

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
`/bulk/s2_remotefile`, `/bulk/pc`.

**None is an IQ / ADC / FFT channel.** `sdr_dump` is a crash/RAM dump and is
disabled. The bulk pipes carry logs, DA logs, crash dumps, remote files, and
firmware flashing.

---

## 8. AMT is manufacturing/calibration/file/auth, not IQ

`dji_amt` is the AMT service (DUSS host `glass:2` = `0x1c02`). Readable command
surface:

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
which we will not exercise.

---

## 9. Why this is not the C5VRX trick

C5VRX (Twotoz) uses an **ESP32-C5** and an undocumented **MODEM_DIAG /
BitScrambler** path to pull IQ from the ESP32-C5's own Wi-Fi/5 GHz PHY, then a
6-bit resistor DAC to make CVBS. The enabler is that the ESP32-C5 has a debug
path reachable from software.

Sparrow2 is different:

- Its AP/CP/DSP/L1C images are encrypted/signed; there is no readable command
  table or register map.
- Its text console (`sdr_shell`) is a **factory-PC** channel (`test:7` =
  `0x1e07`), not an on-device API.
- The AP-side "SDR" configuration is the **digital link**, not IQ:
  `sdr_agent_host_id 0x0e00`, `sdrs_agent_host_id 0x0e04`,
  `sdr_threshold_kbps 4000`, `SDR_ONLY` / `HYBRID_LTE_SDR` link modes, and
  `sdr_rpt_tunnel_map`. These are throughput/tunnel settings.
- The AP-side channels are UART/DA logs and a disabled crash dump.

So the C5VRX *idea* (find the vendor's undocumented debug path) was worth
testing, and we did test it (`sdr_shell`). The result is that Sparrow2's version
of that path is host-gated and its command vocabulary is encrypted. No
equivalent on-device IQ door was found.

## 10. Conclusion

- Sparrow2 definitely produces IQ internally, but the AP has **no exposed
  IQ/ADC/FFT interface** and no documented sample command.
- The shipped console is real, but it is **factory-PC-hosted**, not an
  on-device API. The factory-flag shortcut did not register the test host.
- The AMT/PC protocol is manufacturing/calibration/file/auth, not IQ, and
  touches OTP/secure-debug — out of scope.
- The C5VRX analogy does **not** map cleanly: ESP32-C5 has a ROM `MODEM_DIAG`
  path; Sparrow2's firmware is encrypted and its console is host-gated.
- **No on-goggles software path was found.** Further work would require
  vendor-internal access (the encrypted firmware / factory fixture), outside
  this project's scope.

---

## 11. What was NOT done

- No `/system` writes, dm-verity/partition changes.
- No OTP, RPMB, fuse, bootloader, or SPI/NVRAM writes.
- No firmware decryption, signing bypass, or key extraction/use.
- No AMT OTP/file/secure-debug commands.
- No `sdr_dump` enable.
- No transmit, jamming, spoofing, or third-party interception.

---

## 12. Evidence and tools

- Master summary: `SDR findings/N3-RADIO-PROBE.md`
- Evidence: `SDR findings/device-evidence/2026-11-25_19-42-02/`
  (`factory_console_run.txt`, `console_*.txt`, `amt_*.txt`, `sdr_dump_cfg.txt`,
  `unix_sockets.txt`, …)
- Probes (portable copies in `app/tools/`):
  - `probe_n3_factory_scripts.py`, `probe_n3_factory_scripts2.py`
  - `probe_n3_sdr_console*.py`
  - `probe_n3_factory_precheck.py`, `probe_n3_factory_entry.py`,
    `probe_n3_factory_console.py`
  - `probe_n3_amt_proto.py`, `probe_n3_mb_info.py`, `probe_n3_uart_console.py`
  - `probe_n3_sparrow_diag.py`, `probe_n3_dump.py`, `probe_n3_engpc*.py`
  - `probe_n3_bulk_console.py` (custom `-J` bulk-route console probe)
  - `analyze_sdrs_cfg.py` (offline channel/route analysis)
