# Safety and scope

This project is for the owner's own DJI Goggles N3, on a bench, for UI/theme/
debug development.

## Allowed / implemented

- Session-only root shell via the stock `dji_blackbox` log-export RCE.
- ADB enable/disable via the stock USB composition.
- `/vendor` flat-file mods and theme libs, remounted read-write only during a
  push and set back to read-only afterwards.
- Read-only dmabuf capture and a 160×90 live stream.
- In-goggles app windows composited into the live buffer (no frame
  suppression; the real display call is always made).
- One-click recovery to the stock UI.

## Not done

- No `/system` writes, no dm-verity/partition changes.
- No OTP, RPMB, fuse, bootloader, SPI/NVRAM writes.
- No firmware decryption or key extraction.
- No RF transmit, jamming, spoofing, or interception/decryption of third-party
  traffic.
- No boot persistence; a power cycle restores stock.

## Recovery

1. App → Connection → **Recover stock UI**.
2. Or power-cycle the goggles.
3. Or `py -3.12 -c "import sys; sys.path.insert(0,'app'); import n3ctl;
   n3ctl.start_stock_ui()"`.

## Legal

Use only on hardware you own and in compliance with local radio/computer-misuse
laws. The authors are not responsible for damage or misuse.
