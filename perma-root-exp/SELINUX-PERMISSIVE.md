# SELinux permissive — what it would change

Status: **static analysis, not attempted.** This document explains what
`selinux_state.enforcing = 0` would do, how it could be reached, and what it
would **not** unlock.

## The state

The kernel keeps SELinux state in `struct selinux_state`:

```c
struct selinux_state {
    bool enforcing;      // 1 = Enforcing, 0 = Permissive
    bool checkreqprot;
    bool initialized;
    struct selinux_policy __rcu *policy;
    ...
};
```

The supported userspace path is `security_setenforce()` via
`/sys/fs/selinux/enforce` (the `setenforce` command). The bootloader can set
the initial state with `androidboot.selinux=enforcing|permissive`, exposed as
`ro.boot.selinux`. A policy can mark a domain permissive with
`(permissive <domain>)`.

Factory state on this unit: **Enforcing**, set by the boot cmdline. There is
**no `(permissive ...)` declaration** in the platform or vendor policy.

## Can our root flip it?

Static policy (`plat_sepolicy.cil` + `vendor_sepolicy.cil`):

- `dji_domain` (includes `dji_services`) is explicitly
  `neverallow ... (security (setenforce))`.
- `su` has broad capabilities (`sys_admin`, `sys_rawio`, `sys_ptrace`, ...),
  but **no `(allow su security (setenforce))` rule** was found.
- `shell` has broad file writes but no `setenforce` allow either.
- Only `kernel` has `(allow kernel self (security (setenforce ...)))`.

So `setenforce 0` from the perma-ADB `su` shell or `dji_services` is **denied**
while enforcing. The only routes to permissive are:

1. **Boot cmdline** `androidboot.selinux=permissive` — bootloader-owned;
   changing it means a boot image/bootloader change.
2. **Kernel memory write** — patching `selinux_state.enforcing` directly.
   That is a kernel exploit, not a supported root path; it can crash or be
   detected, and it is not persistent.
3. **Policy change** — add `(permissive su)` or an allow rule to the policy.
   That means writing `/vendor/etc/selinux` (or `/system`), which is a
   boot-chain change; `/vendor` AVB coverage is unproven, `/system` is
   verity-protected.

There is no userspace property or root command that safely flips it.

## What permissive would unlock

Permissive bypasses **SELinux checks only**. DAC permissions, capabilities,
and dm-verity/AVB still apply.

| Operation | Enforcing | Permissive |
|---|---|---|
| Exec `/data` from `dji_services` | denied | allowed (if DAC allows) |
| `mount` / bind mount from `su` | denied by SELinux (`filesystem`/`mounton`) | allowed if `CAP_SYS_ADMIN` (su has it) |
| `chcon` / relabel | denied | allowed if capable |
| Set `sys.usb.config` from `dji_services` | denied (`system_radio_prop`) | allowed (audit only) |
| Start services / access display/GPU/input | policy-dependent | allowed if DAC/caps allow |
| `setenforce` | only kernel | allowed (already permissive) |
| **Raw `/system` write** | **brick** | **still brick** — dm-verity/AVB unaffected |
| **Raw boot/vbmeta/OTP/RPMB write** | off-limits | **still off-limits** |

Permissive would make it much easier to:

- execute `/data` binaries from `dji_services` (patched UI/apps without `su`);
- mount/bind `/data` over system paths **at runtime**;
- write `/vendor` at runtime (if mounted rw);
- set properties and start/stop services.

A runtime bind mount over `/system/...` would be a **session-only overlay**:
the raw verified partition is untouched, so AVB on the next boot still passes;
the overlay disappears on reboot. It is not a persistent `/system` write.

## What it would not unlock

- **`/system` raw writes** — dm-verity mode 2 + AVB still brick on reboot.
- **Boot/vbmeta/partition/OTP/RPMB** — signatures/one-time writes unchanged.
- **Persistence** — reboot returns Enforcing unless the boot cmdline, kernel,
  or policy was changed.
- **Safety** — global permissive weakens every process on the device, not just
  our shell. Audit logs will show `avc: denied ... permissive=1`.

## If you patched `selinux_state` directly

A kernel write to `enforcing = 0` has the same effect as `setenforce 0`:
checks log and allow. It does not change DAC/caps/verity. It is a kernel
exploit, not a supported interface; it may be unstable and is not persistent.
The project does not do this.

## Safe/static next steps

- Read-only: `getenforce`; `cat /sys/fs/selinux/enforce`;
  `getprop ro.boot.selinux`.
- Do **not** run `setenforce 0` expecting it to work; it will be denied.
- Do **not** patch the kernel or write `/vendor/etc/selinux` without proving
  AVB coverage and a recovery path.
- If permissive is ever reached at runtime, test one operation at a time and
  return to Enforcing (`setenforce 1`) before reboot.

## Bottom line

Permissive is a **runtime SELinux bypass**, not a verity bypass. It would
unlock `/data` exec, mount/bind, relabel, and property sets; it would **not**
make `/system` writable or survive a reboot. The current root cannot flip it:
the policy allows only `kernel` to call `setenforce`, and `dji_domain` is
explicitly forbidden. Reaching it needs a boot cmdline, kernel exploit, or
policy change — all boot-chain/security risks, not a casual switch.
