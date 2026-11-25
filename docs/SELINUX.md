# SELinux domain verdict — which compromise is actually useful (2026-11-24)

Scope: static, 0900 rootfs (`firmware/ota/system.img`, `firmware/ota/vendor.img`).
Policy: `/etc/selinux/plat_sepolicy.cil` (system) + `vendor_sepolicy.cil` (vendor).
No device writes.

This pass corrects an earlier note that said `dji_amt` / `dji_services` have
"no shell_exec allow".  The literal token `shell_exec` is not in those rules,
but the rules use the attribute `base_typeattr_350`, which **is** every
exec type except vendor shell/toolbox:

```
(typeattributeset base_typeattr_350_28_0 ((and (exec_type) ((not (vendor_shell_exec_28_0 vendor_toolbox_exec_28_0))))))
```

and `shell_exec`, `toolbox_exec`, `su_exec` are all members of `exec_type`.
So a domain with `base_typeattr_350` can execute `/system/bin/sh`.

## 1. AMT task exec is dead (confirmed)

`dji_amt` (uid 0) can execute **only** its own binary type:

```
(allow dji_amt dji_amt_exec (file (read getattr map execute entrypoint open)))
(allow init_28_0 dji_amt (process (transition)))
(typetransition init_28_0 dji_amt_exec process dji_amt)
```

No `base_typeattr_350`, no `property_service (set)` rule of any kind, and no
`ctl_*` set.  Additionally:

```
(neverallow dji_domain base_typeattr_72_28_0 (security (setenforce)))
(neverallow base_typeattr_97_28_0 security_prop_28_0 (property_service (set)))
```

`dji_domain` contains `dji_amt`, so `setenforce` can never be granted.
Therefore `sys_amt_task_start` -> `popen("<cmd> <param>")` cannot run `/bin/sh`
under the shipped policy.  The live 5-byte `00 00 00 00 00` reply is the
framework echo/`resp_err(0,0,0)`, not proof of execution.  **AMT is a dead
code-exec path on enforcing SELinux.**

## 2. Exec capability by domain

| domain | exec types |
|---|---|
| `dji_amt` | `dji_amt_exec` only |
| `dji_wlm` | `dji_wlm_exec` only |
| `dji_sec` | `dji_sec_exec` only |
| `dji_audio`/`dji_asr`/`dji_squashfs`/`dji_sw_uav`/`dji_gfsk_agent`/`dji_wireless_mic`/`dji_network`/`dji_ml`/`dji_nn_server` | own `*_exec` only |
| `dji_glasses` | `dji_glasses_exec`, `vendor_file` (execute_no_trans) |
| `dji_engpc` | `dji_engpc_exec`, `vendor_file` |
| **`dji_services`** | own exec, `dji_perception_exec`, `vendor_file`, **`base_typeattr_350`** |
| **`start_dji_system`** | own exec, `vendor_file` (rw+x), **`base_typeattr_350`** |
| **`start_dji_camera`** | own exec, `base_typeattr_350` |

`/system/bin/dji_sys` is labelled `dji_services_exec`, so **dji_sys runs in the
`dji_services` domain** and can execute `/system/bin/sh`.  Same for
`dji_blackbox`, `dji_ftpd`, `dji_hms`, `dji_config_store`, `dji_media_server`,
`dji_http_server`, `dji_csdk_server`, `dji_lte`, `dji_agent`, `dji_arhome`,
`dji_network`, `dji_glasses` (binary), `sys_perf_monitor`, etc.

## 3. Property-set capability (for ADB)

Property types (plat_property_contexts):

```
ctl.start           -> ctl_start_prop
sys.usb.config      -> system_radio_prop
service.adb.tcp.port-> shell_prop
```

Who can set what:

| domain | property types it may set |
|---|---|
| `dji_services` | `system_prop`, `default_prop`, `dji_prop`, `logd_prop`, `ctl_default_prop` |
| `start_dji_system` | `system_prop`, `default_prop`, `dji_prop`, `ctl_default_prop` |
| `start_dji_camera` | same shape |
| `dji_sec` | `security_prop` |
| `dji_upgrade` | `system_prop` |
| **`shell`** | **`system_radio_prop`** (`sys.usb.config`) |

Consequences:

* A root shell in `dji_services` **cannot** set `sys.usb.config`
  (`system_radio_prop`) or `ctl.start` (`ctl_start_prop`).
* Only the `shell` domain (and `system_app`/`system_server`) may set
  `sys.usb.config`.
* There is **no** `typetransition` from any `dji_*` domain into `shell` or
  `su`, and **no** `(permissive ...)` declaration in either policy.
* `adbd` is declared with `--root_seclabel=u:r:su:s0`, but the only trigger is
  the `rndis,mass_storage,bulk,acm,adb` property on `init_usb2`.

So a `dji_services` code exec gives uid-0 + shell exec + broad file write, but
ADB itself still needs either (a) a file write into `/vendor/etc/init/*.rc`
plus a reboot (if vendor is rw/unverity), or (b) a transition to `shell`
(does not exist), or (c) `androidboot.secure_debug=1` / `mp_state!=production`.

## 4. Where the remaining value is

* **`dji_sys` (dji_services)** — the only live host-facing parser whose code
  exec yields a working root shell.  Prior copy-sink audits found no reachable
  overflow; the shell sinks fed by device-table names were not reachable from
  the DUML message (device list handler only sets booleans; `net_device_*`
  names come from the kernel/device state machine).
* **`dji_wlm` controlled write** — heap-relative, no ASLR leak.  Only useful
  if it can redirect a *data* pointer (e.g. a `system()` argument) inside
  `dji_wlm` to the 23 attacker bytes already written into the same heap, or
  if `dji_wlm` can write a file consumed by a privileged domain.
* **`dji_amt`** — closed for exec.  Its `00/23` file-recv writes only under
  `/factory_data/` with a filename whitelist; `00/50` SN writes are
  `__memcpy_chk`-bounded.
* **FTP (port 21 is open)** — `dji_ftpd` is `dji_services`, but `PASS` reads
  `/etc/ftp.conf`, which no script in either image creates.  Dead on a retail
  unit unless factory-provisioned.
* **`dji_config_store` tar chain** — `djiconfigstore.rc` triggers on
  `dji.configstore=1`; `product_config.sh` sets `dji.config_store`
  (underscore).  No writer of the correct property.  Dead.

## 5. Corrected bottom line

The useful code-exec target is **`dji_sys` / the `dji_services` domain**, not
`dji_amt` or `dji_wlm`.  A `dji_services` root shell cannot flip ADB by
property, so the post-exploit step must be a boot-persistent write (vendor
init rc) or a direct `adb`-capable transition that does not exist in policy.
