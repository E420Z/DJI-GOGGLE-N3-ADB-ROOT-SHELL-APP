# Third-party notices

## natartos (AGPL-3.0)

The in-goggles mod loader pattern, `natartos_common.h`, and the menu/background
mod sources in this repo are derived from **natartos**, which is licensed under
the GNU Affero General Public License v3.0.

- Upstream: https://github.com/grom-labs/natartos
- License text: `licenses/NATARTOS-AGPL-3.0.txt`
- Notice: `licenses/NOTICE-natartos.txt`

Files that include or derive from `natartos_common.h` (for example
`sdk/n3app.c`, `mods/n3menu`, `mods/n3live`, `mods/capture`, `mods/paint`) are
distributed under AGPL-3.0. If you redistribute a combined work, comply with
the AGPL for those parts.

## DJI binaries

`app/assets/libew_gls_stock.so` and `app/assets/dji_glasses_vendor` are
extracted from the owner's device/firmware. They are **not** part of this
repository and are excluded by `.gitignore`. DJI, Goggles, O4, and related
marks are trademarks of DJI. This project is independent and not endorsed by
DJI.

## Community references

Protocol and UI research referenced in `docs/` includes public work from the
DJI FPV community (natartos, toolya, fpv-wtf, dji-firmware-tools,
`samuelsadok/dji_protocol`, and others). No third-party code is copied here
except the natartos-derived files above.

## OpenMAX IL headers

mods/h264/include/OMX_*.h are the Khronos OpenMAX IL 1.1.2 headers, taken from
the 
aspberrypi/userland mirror. Copyright (c) 2008 The Khronos Group Inc.
Distributed under the Khronos free-use license (MIT-style). Used only to build
the optional hardware H.264 decoder mod.
