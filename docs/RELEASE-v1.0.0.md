# Release notes — v1.0.0 (experimental prerelease)

Published: 2026-11-25  
Release: https://github.com/E420Z/DJI-GOGGLE-N3-ADB-ROOT-SHELL-APP/releases/tag/v1.0.0  
Asset: `N3-ROOT-v1.0.0.zip` (457,433 bytes)  
SHA256: `824EAADC48C37B7B9FCBF3D20B27B474D4F68A82D584CAA1ECCD365A3E15CD00`

Privacy: repository and release are **private**; unauthenticated repo page,
API, release page, and asset all return 404.

## Experimental / crash warnings

- **N3 Menu is experimental/beta.** A previous `displayFrame`-hook build
  **black-screened** on 2026-11-25. Those hooks are compile-time **off** in this
  build; the shipped menu uses the conservative thread compositor + input
  suppression.
- **Paint overlay** is a proof of concept only.
- **Experimental `DisplayEngine` hooks are OFF. Do not enable them yet.**
- Legacy natartos G3 `menu` / `popen` / `template` mods were **removed**
  (unsafe on N3).
- **If the screen goes black:** Connection → **Recover stock UI**, or
  power-cycle. Nothing is installed in the boot chain.

Full table: [`EXPERIMENTAL.md`](EXPERIMENTAL.md).

## Verified

- Live preview: 160×90, ~59 fps (290 frames in 5 s).
- Full 1920×1080 screenshots via the safe dmabuf hook.
- Theme build produces a 103,984,504-byte patched lib.
- App builds; smoke test passes.

## Run

1. Install Python 3.12 and `pip install -r requirements.txt`.
2. Double-click **Start N3 ROOT.cmd** (Windows).
3. Connection → **Start root** → **Enable ADB**.
4. E42OZ → **Start live**.

## Not included (add locally)

- `app/assets/libew_gls_stock.so` and `app/assets/dji_glasses_vendor` are DJI
  binaries and are **not** in git/release. Theme building needs them; see the
  README.
- No `/system`, dm-verity, OTP/RPMB, or bootloader changes.
