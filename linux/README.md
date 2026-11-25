# Linux backup / recovery

The main N3 ROOT app is Windows-first because the `dji_blackbox` root-shell
transport uses libusb0 on Windows. On Linux this small CLI is the safety net.

It works over **ADB** (enable ADB first from Windows, or use the app once).

```sh
python3 linux/n3backup.py info
python3 linux/n3backup.py backup --out ~/n3-backups
python3 linux/n3backup.py restore --from ~/n3-backups/n3-backup-YYYY-mm-dd_HH-MM-SS
python3 linux/n3backup.py reboot
```

- `backup` pulls the `/vendor` mod/theme files and the `/data/local/tmp`
  loader list into a timestamped folder with a manifest.
- `restore` pushes them back. `/vendor` must be writable (root/ADB root); the
  CLI tries `mount -o remount,rw /vendor` and reports failures.
- `reboot` is the simplest recovery: nothing is installed in the boot chain, so
  the stock UI returns after a power cycle.

The 100 MB `/vendor/libew_gls.so` is skipped by default; add
`--with-theme-lib` if you want a full theme rollback.

No `/system`, verity, OTP/RPMB, or bootloader operations are performed.
