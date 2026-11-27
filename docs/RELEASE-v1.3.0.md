# Release notes — v1.3.0

Published: 2026-11-27
Tag: `v1.3.0`

**Tested on DJI Goggles N3 firmware 0900 only.** 1.09 remains untested; this
release makes the failure *diagnosable*, not 1.09 rootable.

## What changed

### Find N3 is now deterministic

A new **Connection → Find N3** action replaces subnet guessing:

1. Enumerate Windows PnP for **`USB\VID_2CA3*`**. No match means the goggles are
   not on USB; the action says exactly that.
2. Pick the **Net-class child** whose PnP ID is `USB\VID_2CA3&PID_0020&MI_00`.
   That is the RNDIS adapter, matched by hardware ID, not by its name.
3. Read only that adapter's IPv4/prefix and its ARP neighbours
   (`Get-NetNeighbor`). The goggles' IP comes from the neighbour table.
4. Probe TCP 4444 on the neighbour(s), then `.2`/`.129`/`.1` of that adapter's
   /24, then sweep **only that /24** if needed.

It never falls back to Wi-Fi, VPN or a wired LAN. A `192.168.68.x` adapter is
only scanned when Windows says it is the `VID_2CA3` device.

The result is one of four honest stages:

| Stage | Meaning |
|---|---|
| `no_device` | No `VID_2CA3` USB device. Cable/port/power. |
| `no_rndis` | USB present, but no `MI_00` network interface. RNDIS driver or USB mode. |
| `no_shell` | N3 found, RNDIS up, **nothing listening on 4444** → payload/nc/SELinux or 1.09. |
| `shell_up` | Root shell found at the reported IP. |

The same summary is shown on the Connection page under **N3 link**.

### Honest failure reporting

- `start_root()` now checks USB/RNDIS **before** the exploit and prints a
  specific message instead of scanning random networks.
- If the RNDIS adapter is up but 4444 is silent, the log now says that the
  payload was accepted but did not bind — pointing at firmware/nc/SELinux, not
  at the network.
- The classic Tk log no longer prints `✔` when an action returned `False`
  (the pywebview path already reported the failure).

### Fixes

- `goggles_adapter()` now uses `Get-NetAdapter.PnpDeviceID`. On current Windows,
  `Get-NetAdapterHardwareInfo` did not return the ID, so the adapter could be
  missed even though `Get-NetAdapter` showed it.
- Neighbour discovery filters broadcast (`x.x.x.255`), permanent, incomplete and
  `169.254.x` entries, so only real hosts are probed.

## Verified

On the owner's N3, firmware 0900, stock UI:

```
USB interfaces: 8 (VID_2CA3)
RNDIS adapter : Ethernet 2 (Remote NDIS based Internet Sharing Device)
IPv4          : 192.168.60.1/24
Neighbors     : 192.168.60.2 DE-F4-6B-AA-98-C7
Port 4444     : closed everywhere
→ stage no_shell
```

Simulated no-adapter run: `_local_ipv4()` returns `[]`, the sweep refuses with
“No N3 RNDIS adapter; refusing to scan other networks,” and `Find N3` reports
`no_rndis`.

## Unchanged

- Goggles Stream is still 1920×1080 at 59–60 fps, H.264 from the vc8000e,
  10 Mbps vendor pipe cap, MSE viewer with telemetry rail.
- No `/system` writes, no boot-chain changes, no radio transmit.
- Root remains the session-only `dji_blackbox` RCE; **Recover stock UI** and a
  reboot always restore stock.

## Known limits

- **1.09 root is still unverified.** If the RNDIS adapter is present and
  `ack=c0` arrives but no listener appears, the `dji_blackbox` path/offsets are
  the likely difference. Keep that build's `/system/bin/dji_blackbox` for
  comparison; do not loop the exploit.
- 60 Mbps goggles → PC and the H.264 PC → goggles display path remain research
  and are not enabled in the app.
