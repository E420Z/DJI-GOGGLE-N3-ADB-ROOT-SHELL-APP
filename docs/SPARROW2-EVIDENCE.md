# Sparrow2 — verbatim evidence appendix

This is the raw evidence behind [`SPARROW2.md`](SPARROW2.md). Device-specific
files live in the local (uncommitted) evidence folder
`SDR findings/device-evidence/2026-11-25_19-42-02/`.

---

## 1. Console query from a normal root shell

Baseline `sdr_shell help` (the wrapper hides the transport error):

```
cmd help no response
```

Raw `dji_mb_ctrl` with the same payload (before passing `-m`):

```
Send message, from machine 0x900 host 1e07, to machine 0 host 0e00,
msg_id: 00090055, attrib: 00001040, len: 9, seq_id: 5, data:
  00 64 00 18 68 65 6c 70 0d
duss_event_send_sync_v2() error: -1002
operation fail, error: -1002
```

Keys: `00 64 00 18` = console prefix, `68 65 6c 70 0d` = `help\r`.

With `-m 2304` (the goggles' own machine) the error changes to:

```
Send message, from machine 0x900 host 1e07, to machine 0x2304 host 0e00,
msg_id: 00090055, attrib: 00001040, len: 9, seq_id: 19, data:
  00 64 00 18 68 65 6c 70 0d
duss_event_send_sync_v2() error: -1007
operation fail, error: -1007
```

Device logs map `-1002` to a DUSS **router error**:

```
F DUSS41  : [LINK_DEBUG-MB_FORWARD-N/A] Router error -1002 on host 1c01.
```

---

## 2. Live DUSS hosts (normal mode)

From `/proc/net/unix`:

```
@/duss/mb/0x0
@/duss/mb/0x1704
@/duss/mb/0x1c00
@/duss/mb/0x1c01
@/duss/mb/0x1c02
@/duss/mb/0x1c04
@/duss/mb/0x1c05
@/duss/mb/0x1c06
@/duss/mb/0x1c07
@/duss/mb/0x1d02
@/duss/mb/0x1f00
@/duss/mb/0x500
@/duss/mb/0xe03
@/duss/mb/0xe04
@/duss/mb/0xe07
```

**No `0x1e07`.** That is the `test:7` host `sdr_shell` uses. `dji_amt` owns
`0x1c02`; `dji_sys` owns `0x1c01`.

---

## 3. Factory-flag attempt (and recovery)

Snapshot / flag:

```
386db554c78e047335680dd7cdc29ee9  /data/us.db
-rw------- 1 root root 0 2026-11-25 20:53 /data/dji/cfg/in_factory
```

After `setprop dji.amt_service 0` → `1` and `sdr_shell help`/`?`/`version`/
`info`/`peer help`:

```
cmd help no response
cmd ? no response
cmd version no response
cmd info no response
cmd help no response
```

Recovery (flag removed, service restarted):

```
-rw------- 1 root root 0 2026-11-12 02:18 in_factory_oneshot
386db554c78e047335680dd7cdc29ee9  /data/us.db
sys.usb.config = rndis,mass_storage,bulk,acm
ui = {'stock': True, 'patched': False, ...}
```

Conclusion: the file does not register the PC test host. The real entry is the
PC AMT request (`factory_debug: get request from PC, cmd is [%s]`).

---

## 4. SDRS channel inventory

`sdrs_agent_service.configuration.sdrs_log.channel`:

```
uart_log_in     uart        /dev/ttyS1 921600    status 1
uart_log_store  dls                               status 1
modem_da_log    bulk_single /bulk/s2_da  iface 7 ep 88/08  status 1
da_log_out      socket      -> modem_da_log       status 0
sdr_dump        bulk_single /bulk/s2_sdrdump iface 6 ep 87/07 status 0
dump_store      dump_v1                          status 0
ap_crash_store  dls                              status 0
cp_crash_store  dls                              status 0
l1c_crash_store dls                              status 0
dsp_crash_store dls                              status 0
```

Other HAL bulk devices:

```
/bulk/s2
/bulk/e3t_sys-s2_hs
/bulk/s2_sdrdump
/bulk/s2_da
/bulk/s2_remotefile
/bulk/pc
```

No IQ/ADC/FFT/sample channel.

---

## 5. Sparrow2 firmware inventory

```
/vendor/modem_firmware/sparrow2/
  ap.img  cp.img  dsp.img  l1c.img  scp.img  pwr.bin  ipc.bin
  bootarea.img  amt.bin  cp_nvram.bin  rf_nvram.bin  share_info.bin
  wa020/ wa520/ wa521/ wa530/ za530_lite/ za530_pro/
```

`strings` on the images returns only random fragments — encrypted/signed.

---

## 6. Factory scripts present

```
/system/bin/sdr_shell
/system/bin/test_sparrow2_link.sh
/system/bin/test_sparrow2_tsync.sh
/system/bin/test_sparrow2_hw_ver.sh
/system/bin/test_reset_s2_link.sh
/system/bin/test_sdrlog_e3t_uart5_link.sh
/system/bin/test_rf.sh
/system/bin/pro_sparrow2_0.sh
/system/bin/get_upload_sparrow2_0.sh
/system/bin/burn_otp_sparrow2_0.sh
```

`test_rf.sh` only checks the CP-state aging counter in the SDRUART log; it is
not a spectrum/IQ test.

---

## 7. AMT command strings (no IQ)

```
sys_amt_get_serial_number / sys_amt_set_serial_number
sys_amt_task_get_log / sys_amt_task_get_result
sys_amt_file_recv_req_proc / sys_amt_file_send_proc   (CRC32, OTP file recv)
sys_amt_audio_factory_test                             (speaker CALIB/Play/Stop)
sys_amt_task_check_securedebug_auth
sec_cmd_act_send_onetime_auth / sec_cmd_verify_onetime_msg
start_factory / start_factory_oneshot / stop_factory
set_ssd_from_factory / reset_ssd_from_factory
sys_amt_task_generate_auth_msg
```

No `iq`, `sample`, `adc`, `spectrum`, `rf_read`, or `dump_iq` symbol.

`/system/etc/commands.json` maps `0x55` to the **`hdvt`** set
(`{"cmdid":"0x55","req":"yes","ack":"null","flags":"zero"}`), i.e. an HDVT
(digital video link) debug command, not an RF/IQ set.

---

## 8. Safety boundary

Nothing above is a write to `/system`, a partition, OTP/RPMB, a fuse, the
bootloader, or SPI/NVRAM. No firmware decryption or key extraction was done.
The factory-flag test only touched `/data/dji/cfg/in_factory` and was reverted.
