# Release notes — v1.2.1

Published: 2026-11-27
Tag: `v1.2.1`

**Tested on DJI Goggles N3 firmware 0900 only.** 1.09 remains untested; this
release adds address/network recovery and diagnostics, not a verified 1.09
exploit.

## What changed

### Root shell finds the goggles network itself

The helper now identifies the **DJI RNDIS adapter by USB PnP ID**
(`VID_2CA3`) and only ever configures that adapter. It never touches Wi-Fi,
VPN/Tailscale or a normal Ethernet adapter.

- **APIPA / no DHCP.** If the adapter only has a `169.254.x` address, it runs
  `ipconfig /renew` once. If that fails it temporarily adds **`192.168.60.1/24`**,
  then **`192.168.42.1/24`**, then **`192.168.137.1/24`** to that adapter and
  sweeps the /24 for port 4444. The first address that answers is adopted.
- **Full /24 sweep** for a normal lease too, so a DHCP-assigned address such as
  `192.168.68.100` is found without knowing it in advance.
- **Temporary addresses are removed** on *Stop root* and on app exit. Wi-Fi,
  VPN and LAN subnets are excluded from all scans.
- Needs **administrator** to add an address. If Windows refuses, the log says
  so and prints the equivalent `netsh` command.

Example log:

```
Goggles RNDIS adapter 'Ethernet 3' has no DHCP lease (169.254.154.244); renewing...
Still no DHCP lease; will try static RNDIS subnets after the payload.
Trying 192.168.60.1/24 on 'Ethernet 3'...
Root shell found at 192.168.60.2:4444.
```

### More robust RCE fallback

- If the minimal DUML handshake produces no listener, the RCE is retried after
  the **full DUML session init** (the DJI-Assistant-style init used for file
  reads).
- The shell command now tries `/system/xbin/busybox`, `/system/bin/busybox`,
  then `/system/bin/toybox` (156 bytes, under the 255-byte RCE limit).
- `ack=c0` is still not proof of execution. **`handshake replies: 0` is a red
  flag**: a working 0900 prints `1`. On 1.09 the `dji_blackbox` path may differ;
  if no listener appears on any local RNDIS address after both attempts, keep
  that build's `/system/bin/dji_blackbox` for a comparison.

### Unchanged

- **Goggles Stream** is the same as 1.2.0: 1920×1080 at 59–60 fps, H.264 from
  the vc8000e, no re-encode, 10 Mbps vendor pipe cap, MSE viewer with telemetry
  rail and fullscreen.
- No `/system` writes, no boot-chain changes, no radio transmit.

## Safety

- Network changes are **host-side and scoped to the DJI adapter** by USB ID;
  existing addresses are not removed, and temporary ones are removed on stop.
- Device writes remain `/vendor` (remounted rw for the push, then ro) and
  `/data/local/tmp` only.
- Root shell is the stock `dji_blackbox` RCE, session-only; **Recover stock UI**
  and a reboot always restore stock.

## Quick start

1. Run the app **as administrator** (needed only for the APIPA fallback).
2. Connection → **Start root**. Watch the adapter/renew/sweep lines.
3. **Goggles Stream** → **Start stream** (install ffmpeg first).

## Known limits

- 1.09 root is unverified; if `handshake replies: 0` and no listener appears on
  any local RNDIS address after both attempts, the payload target likely changed.
- Goggles Stream is **10 Mbps** maximum (read-only `/system` pipe).
- 60 Mbps remains research only and is not shipped.
- Firmware 0900 only for the tested paths.
