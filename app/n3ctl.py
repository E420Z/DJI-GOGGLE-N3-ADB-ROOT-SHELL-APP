"""n3ctl.py - PC-side control for DJI Goggles N3 root shell + ADB.

Everything here is reversible:
  * root shell = the stock dji_blackbox log-export RCE (listener on :4444)
  * ADB       = stock `rndis,mass_storage,bulk,acm,adb` USB composition
  * restore   = stock `rndis,mass_storage,bulk,acm`

No /system or /vendor writes.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(APP_DIR, "tools")
sys.path.insert(0, TOOLS)

import spawn_shell          # noqa: E402
import libusb0_dji as L     # noqa: E402

_EXPLICIT_HOST = os.environ.get("N3_HOST")
HOST = _EXPLICIT_HOST or "192.168.60.2"
PORT = 4444
RCV_PORT = 9010
VID = 0x2CA3

# Kills the temporary :4444 listener and its respawn subshell without needing# a second root-shell connection. Runs through the same dji_blackbox RCE.
STOP_RCE = (
    r"""foo;for i in 1 2 3;do """
    r"""p=$(netstat -tlnp|grep ':4444 '|head -1|sed 's/.* \([0-9]*\)\/.*/\1/');"""
    r"""[ -z "$p" ]&&break;pp=$(cut -d' ' -f4 /proc/$p/stat);"""
    r"""kill -9 $p $pp;sleep 1;done"""
)

ADB_CANDIDATES = [
    r"C:\platform-tools\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"),
]

UI_BIN = "/vendor/dji_glasses_patched"
UI_LIB = "/vendor/libew_gls.so"
MODS_LOADER = "/vendor/n3mods.so"
MODS_LIST = "/data/local/tmp/n3mods.list"
BG_HOOK = "/vendor/n3bg.so"
TINT_HOOK = "/vendor/n3_texttint.so"
EWTRACE_HOOK = "/vendor/n3_ewtrace.so"
BITMAP_HOOK = "/vendor/n3_bitmap.so"
BG_IMAGE = "/vendor/background.jpg"
BG_IMAGE_IDLE = "/vendor/background_idle.jpg"

STOP_UI = (
    "setprop ctl.stop dji_glasses; sleep 1; "
    "for p in $(ps -A | grep dji_glasses | tr -s ' ' | cut -d' ' -f2); "
    "do kill -9 $p 2>/dev/null; done; sleep 1"
)


def _noop(_msg):
    pass


# ---------------------------------------------------------------- root shell

# The goggles' RNDIS address is not guaranteed to be 192.168.60.2 (a different
# firmware or a Windows ICS adapter can move the subnet). Discover it from the
# PC's own RNDIS/USB IPv4 subnet instead of relying on one hardcoded address.
_LOCAL_IPS = None
_LOCAL_AT = 0.0
_SCAN_LOCK = threading.Lock()
_SCAN_AT = 0.0
_SCANNING = False


def _local_ipv4():
    """IPv4 addresses of the PC's RNDIS/USB adapters (cached 20 s)."""
    global _LOCAL_IPS, _LOCAL_AT
    now = time.time()
    if _LOCAL_IPS is not None and now - _LOCAL_AT < 20:
        return _LOCAL_IPS
    ips = []
    try:
        cmd = (
            "Get-CimInstance Win32_NetworkAdapterConfiguration "
            "-Filter 'IPEnabled=TRUE' | ForEach-Object { "
            "$_.Description + '|' + ($_.IPAddress -join ',') }"
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=6)
        entries = []
        for line in (r.stdout or "").splitlines():
            desc, _sep, addrs = line.strip().partition("|")
            v4 = [ip for ip in addrs.split(",")
                  if ip.count(".") == 3 and not ip.startswith("169.254.")]
            if v4:
                entries.append((desc.lower(), v4))
        preferred = [ip for desc, v4 in entries
                     if any(k in desc for k in ("rndis", "remote ndis", "usb"))
                     for ip in v4]
        ips = preferred or [ip for _desc, v4 in entries for ip in v4]
    except Exception:  # noqa: BLE001
        ips = []
    _LOCAL_IPS = ips
    _LOCAL_AT = now
    return ips


def candidate_hosts():
    """Likely goggles addresses: explicit override, then local /24 .2/.1/.129."""
    if _EXPLICIT_HOST:
        return [_EXPLICIT_HOST]
    local = _local_ipv4()
    out = ["192.168.60.2"]
    for ip in local:
        base = ".".join(ip.split(".")[:3])
        for last in ("2", "1", "129"):
            host = "%s.%s" % (base, last)
            if host in local:          # never probe the PC itself
                continue
            if host not in out:
                out.append(host)
    return out


def _probe_host(host: str, timeout: float = 0.35) -> bool:
    try:
        s = socket.create_connection((host, PORT), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def find_root(timeout: float = 8.0, log=_noop) -> bool:
    """Find the running shell, scanning local RNDIS subnets if needed."""
    global HOST
    if _probe_host(HOST):
        return True
    cands = candidate_hosts()
    log("Scanning for the root shell: %s" % ", ".join(cands))
    end = time.time() + timeout
    while time.time() < end:
        for host in cands:
            if host == HOST:
                continue
            if _probe_host(host):
                HOST = host
                log("Root shell found at %s:%d." % (HOST, PORT))
                return True
        time.sleep(0.25)
    return False


def maybe_discover() -> None:
    """Background scan, throttled, so status can recover a moved address."""
    global _SCAN_AT, _SCANNING
    now = time.time()
    with _SCAN_LOCK:
        if _SCANNING or now - _SCAN_AT < 10:
            return
        _SCAN_AT = now
        _SCANNING = True

    def work():
        global _SCANNING
        try:
            find_root(4.0, _noop)
        finally:
            with _SCAN_LOCK:
                _SCANNING = False

    threading.Thread(target=work, daemon=True).start()


def is_root() -> bool:
    try:
        s = socket.create_connection((HOST, PORT), timeout=1.5)
        s.close()
        return True
    except OSError:
        maybe_discover()
        return False


def run_root(cmd: str, timeout: float = 8.0, retries: int = 0) -> str:
    """Run one command through the root shell and return its output."""
    last = None
    for _attempt in range(retries + 1):
        s = None
        try:
            s = socket.create_connection((HOST, PORT), timeout=3.0)
            s.settimeout(timeout)
            marker = "__N3_%d__" % time.time_ns()
            s.sendall((cmd + "\necho " + marker + "\n").encode())
            data = b""
            while True:
                try:
                    chunk = s.recv(8192)
                except socket.timeout:
                    break
                if not chunk:
                    break
                data += chunk
                if marker.encode() in data:
                    break
            return data.decode("utf-8", "replace").replace(marker, "").strip()
        except OSError as exc:
            last = exc
            time.sleep(0.35)
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
    raise last


def start_root(log=_noop) -> bool:
    """Start the root shell via the stock dji_blackbox RCE."""
    if find_root(2.0, log):
        log("Root shell is already running on %s:%d." % (HOST, PORT))
        return True
    log("Sending root-shell payload via dji_blackbox...")
    rc, out = spawn_shell.send(spawn_shell.SHELL_CMD, wait_ms=1800)
    acks = ", ".join("ack=%02x" % ack for ack, _ in out) or "no reply"
    log("RCE reply: %s" % acks)
    if find_root(10.0, log):
        log("Root shell is up: %s:%d (uid 0, dji_services)." % (HOST, PORT))
        return True
    log("Root shell did not answer on any local RNDIS address (tried %s)."
        % ", ".join(candidate_hosts()))
    log("Check that the goggles' RNDIS adapter is present in ipconfig, and that "
        "the firmware matches a tested build (0900).")
    return False


def push_file(local: str, remote: str, log=_noop, port: int = RCV_PORT) -> bool:
    """Push a file over the RNDIS link through a temporary nc receiver."""
    if not is_root():
        raise RuntimeError("root shell is not running")
    size = os.path.getsize(local)
    log("Pushing %s (%d bytes)..." % (os.path.basename(local), size))
    run_root(
        "(setsid /system/xbin/busybox nc -l -p %d > %s 2>/dev/null </dev/null &); echo started"
        % (port, remote),
        timeout=5,
        retries=2,
    )
    time.sleep(0.6)
    h = hashlib.sha256()
    s = socket.create_connection((HOST, port), timeout=8)
    s.settimeout(20)
    try:
        with open(local, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                s.sendall(chunk)
                h.update(chunk)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    finally:
        s.close()
    time.sleep(0.3)
    out = run_root("sha256sum %s" % remote, timeout=8, retries=2).strip().split()
    got = out[0] if out else ""
    if got != h.hexdigest():
        raise RuntimeError("SHA-256 mismatch on %s (%s != %s)" % (remote, got, h.hexdigest()))
    log("Verified %s (sha256 %s...)." % (remote, got[:12]))
    return True


def stop_root(log=_noop) -> bool:
    """Kill the temporary root shell and its respawn wrapper."""
    if not is_root():
        log("Root shell is already stopped.")
        return True
    log("Stopping root shell...")
    try:
        spawn_shell.send(STOP_RCE, wait_ms=1500)
    except Exception as exc:  # noqa: BLE001
        log("RCE stop failed: %s" % exc)
    time.sleep(2.0)
    ok = not is_root()
    log("Root shell stopped." if ok else "Root shell is still answering on :4444.")
    return ok


# ---------------------------------------------------------------------- ADB

def find_adb():
    p = shutil.which("adb")
    if p:
        return p
    for cand in ADB_CANDIDATES:
        if cand and os.path.exists(cand):
            return cand
    return None


def adb_devices(adb=None):
    adb = adb or find_adb()
    if not adb:
        return []
    try:
        r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=12)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def adb_shell(cmd: str, adb=None, timeout: float = 15.0) -> str:
    adb = adb or find_adb()
    if not adb:
        return ""
    try:
        r = subprocess.run([adb, "shell", cmd], capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return "adb shell failed: %s" % exc


def enable_adb(log=_noop) -> dict:
    """Switch USB to the adb composition and wait for a root adb shell."""
    if not is_root() and not start_root(log=log):
        raise RuntimeError("root shell is not available")
    push_file(os.path.join(TOOLS, "usb_adb.sh"), "/data/local/tmp/usb_adb.sh", log=log)
    log("Switching USB to rndis,mass_storage,bulk,acm,adb (link will drop)...")
    try:
        run_root(
            "chmod 755 /data/local/tmp/usb_adb.sh; "
            "setsid sh /data/local/tmp/usb_adb.sh >/dev/null 2>&1 &",
            timeout=2,
        )
    except OSError:
        pass

    adb = find_adb()
    if not adb:
        raise RuntimeError(
            "adb.exe not found. Install platform-tools or set PATH, then try again."
        )
    log("Waiting for adb... (%s)" % adb)
    for _ in range(60):
        devs = adb_devices(adb)
        if devs:
            log("ADB device: %s (%s)" % devs[0])
            ident = adb_shell("id", adb)
            log(ident)
            return {"adb": adb, "devices": devs, "id": ident}
        time.sleep(1)
    log("ADB did not appear within 60 s.")
    log("The switch script should have reverted USB. If the goggles show an ADB")
    log("interface without a driver in Device Manager, install WinUSB (Zadig).")
    return {"adb": adb, "devices": [], "id": ""}


def restore_stock(log=_noop) -> bool:
    """Switch USB back to the stock non-adb composition and stop adbd."""
    if not is_root() and not start_root(log=log):
        raise RuntimeError("root shell is not available")
    push_file(os.path.join(TOOLS, "stock_usb.sh"), "/data/local/tmp/stock_usb.sh", log=log)
    log("Restoring stock USB (rndis,mass_storage,bulk,acm)...")
    try:
        run_root(
            "chmod 755 /data/local/tmp/stock_usb.sh; "
            "setsid sh /data/local/tmp/stock_usb.sh >/dev/null 2>&1 &",
            timeout=2,
        )
    except OSError:
        pass
    time.sleep(4.0)
    devs = adb_devices() if find_adb() else []
    log("Stock USB restored; adb devices: %d." % len(devs))
    return not devs


# ------------------------------------------------------- UI / theme / mods

def dev_exists(path: str) -> bool:
    if not is_root():
        return False
    try:
        return run_root("test -e %s && echo 1 || echo 0" % shlex.quote(path),
                        timeout=6, retries=1).strip().endswith("1")
    except Exception:
        return False


def ensure_adb(log=_noop):
    """Return an adb path, switching the USB composition only if needed."""
    if adb_devices():
        return find_adb()
    res = enable_adb(log=log)
    return res.get("adb") or find_adb()


@contextlib.contextmanager
def vendor_write(log=_noop):
    """Remount /vendor rw, provide a dji_services root shell, then undo it."""
    ensure_adb(log)
    log("Remounting /vendor read-write...")
    adb_shell("mount -o remount,rw /vendor", timeout=20)
    if not start_root(log):
        raise RuntimeError("root shell is not available")
    try:
        yield
    finally:
        try:
            stop_root(log)
        except Exception:
            pass
        adb_shell("sync; mount -o remount,ro /vendor", timeout=20)
        try:
            restore_stock(log)
            stop_root(log)
        except Exception as exc:  # noqa: BLE001
            log("USB restore warning: %s" % exc)


def ui_state() -> dict:
    st = {
        "root": is_root(), "pid": "", "patched": False, "stock": False,
        "theme": False, "loader": False, "background": False, "mods": False,
        "tint": False, "ewtrace": False, "bitmap": False,
    }
    if not st["root"]:
        return st
    cmd = (
        "echo THEME=$(test -f %s && echo 1 || echo 0); "
        "echo LOADER=$(test -f %s && echo 1 || echo 0); "
        "echo BG=$(test -f %s && test -f %s && test -f %s && echo 1 || echo 0); "
        "echo MODS=$(test -f %s && echo 1 || echo 0); "
        "echo TINT=$(test -f %s && echo 1 || echo 0); "
        "echo EWTRACE=$(test -f %s && echo 1 || echo 0); "
        "echo BITMAP=$(test -f %s && echo 1 || echo 0); "
        "echo PPID=$(ps -A | grep dji_glasses_pat | head -1 | "
        "tr -s ' ' | cut -d' ' -f2); "
        "echo SPID=$(ps -A | grep -E ' dji_glasses$' | head -1 | "
        "tr -s ' ' | cut -d' ' -f2)"
        % (UI_LIB, UI_BIN, BG_HOOK, BG_IMAGE, BG_IMAGE_IDLE, MODS_LOADER,
           TINT_HOOK, EWTRACE_HOOK, BITMAP_HOOK)
    )
    try:
        out = run_root(cmd, timeout=12, retries=1)
    except Exception:
        return st
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if k in ("THEME", "LOADER", "BG", "MODS", "TINT", "EWTRACE", "BITMAP"):
            st[{"THEME": "theme", "LOADER": "loader", "BG": "background",
                "MODS": "mods", "TINT": "tint", "EWTRACE": "ewtrace",
                "BITMAP": "bitmap"}[k]] = v.endswith("1")
        elif k == "PPID" and v:
            st["pid"], st["patched"] = v, True
        elif k == "SPID" and v:
            st["pid"], st["stock"] = v, True
    return st


def start_ui(log=_noop, mods=None) -> bool:
    """Start the patched UI (or stock with hooks) and verify it."""
    if not is_root() and not start_root(log):
        return False
    have_theme = dev_exists(UI_LIB) and dev_exists(UI_BIN)
    have_bg = (dev_exists(BG_HOOK) and dev_exists(BG_IMAGE)
               and dev_exists(BG_IMAGE_IDLE))
    have_loader = dev_exists(MODS_LOADER)
    have_tint = dev_exists(TINT_HOOK)
    have_ewtrace = dev_exists(EWTRACE_HOOK)
    have_bitmap = dev_exists(BITMAP_HOOK)

    mods = [m for m in (mods or []) if m]
    if mods and not have_loader:
        log("Mod loader is not installed; starting without mods.")
        mods = []
    if mods:
        args = " ".join(shlex.quote(m) for m in mods)
        run_root("printf '%%s\\n' %s > %s" % (args, MODS_LIST),
                 timeout=6, retries=1)
    else:
        run_root("rm -f %s" % MODS_LIST, timeout=6, retries=1)

    preloads = []
    # The bitmap probe must come before the tint so it sees the real UI caller;
    # it chains to the tint wrapper via RTLD_NEXT.
    if have_bitmap:
        preloads.append(BITMAP_HOOK)
    if have_tint:
        preloads.append(TINT_HOOK)
    if have_ewtrace:
        preloads.append(EWTRACE_HOOK)
    if mods:
        preloads.append(MODS_LOADER)
    if have_bg:
        preloads.append(BG_HOOK)

    env = ""
    if have_theme:
        env += "LD_LIBRARY_PATH=/vendor "
    if preloads:
        env += "LD_PRELOAD=%s " % ":".join(preloads)
    binary = UI_BIN if have_theme else "/system/bin/dji_glasses"
    log("Starting %s%s..." % (
        "patched UI" if have_theme else "stock UI",
        " with " + ", ".join(os.path.basename(x) for x in preloads)
        if preloads else ""))

    cmd = (
        "%s; %ssetsid %s -g -f >/data/local/tmp/dji_glasses.log 2>&1 "
        "</dev/null & sleep 6; "
        "p=$(ps -A | grep dji_glasses_pat | head -1 | tr -s ' ' | "
        "cut -d' ' -f2); "
        "[ -z \"$p\" ] && p=$(ps -A | grep -E ' dji_glasses$' | "
        "head -1 | tr -s ' ' | cut -d' ' -f2); "
        "echo N3PID=$p; "
        "[ -n \"$p\" ] && grep -a -e libew_gls -e n3mods -e n3bg -e n3_texttint -e n3_ewtrace -e n3_bitmap "
        "/proc/$p/maps; "
        "tail -6 /data/local/tmp/dji_glasses.log; "
        "if [ -z \"$p\" ]; then setprop ctl.start dji_glasses; "
        "echo FALLBACK_STOCK; fi"
        % (STOP_UI, env, binary)
    )
    try:
        out = run_root(cmd, timeout=35, retries=1)
    except Exception as exc:  # noqa: BLE001
        log("UI start failed: %s" % exc)
        return False
    log(out)
    pid = ""
    if "N3PID=" in out:
        pid = out.split("N3PID=", 1)[1].splitlines()[0].strip()
    return bool(pid) and "FALLBACK_STOCK" not in out


def start_stock_ui(log=_noop) -> bool:
    if not is_root() and not start_root(log):
        return False
    log("Starting stock UI...")
    out = run_root(
        "%s; setprop ctl.start dji_glasses; sleep 3; "
        "echo N3PID=$(ps -A | grep -E ' dji_glasses$' | head -1 | "
        "tr -s ' ' | cut -d' ' -f2)" % STOP_UI,
        timeout=25, retries=1)
    log(out)
    return "N3PID=" in out and out.split("N3PID=", 1)[1].strip() != ""


def install_theme(lib_path: str, log=_noop, mods=None) -> bool:
    """Deploy a built libew_gls.so, ensure the loader, and restart the UI."""
    if not os.path.exists(lib_path):
        raise RuntimeError("theme lib not found: %s" % lib_path)
    loader = os.path.join(APP_DIR, "assets", "dji_glasses_vendor")
    ensure_adb(log)
    log("Remounting /vendor read-write...")
    adb_shell("mount -o remount,rw /vendor", timeout=20)
    if not start_root(log):
        raise RuntimeError("root shell is not available")
    try:
        log("Stopping the current UI...")
        run_root(STOP_UI, timeout=15, retries=1)
        push_file(lib_path, UI_LIB, log=log)
        if not dev_exists(UI_BIN):
            push_file(loader, UI_BIN, log=log)
        run_root("chmod 755 %s" % UI_BIN, timeout=6, retries=1)
    finally:
        try:
            stop_root(log)
        except Exception:
            pass
        adb_shell("sync; mount -o remount,ro /vendor", timeout=20)
        try:
            restore_stock(log)
            stop_root(log)
        except Exception as exc:  # noqa: BLE001
            log("USB restore warning: %s" % exc)
    return start_ui(log, mods=mods)


def revert_stock(log=_noop) -> bool:
    """Remove the N3 theme/loader/background/mod files and start stock."""
    ensure_adb(log)
    log("Remounting /vendor read-write...")
    adb_shell("mount -o remount,rw /vendor", timeout=20)
    if not start_root(log):
        raise RuntimeError("root shell is not available")
    try:
        run_root(STOP_UI, timeout=15, retries=1)
        run_root(
            "rm -f %s %s %s %s %s %s %s %s %s /vendor/hook_menu.so "
            "/vendor/hook_popen.so /vendor/mod_template.so; "
            "rm -f %s; sync"
            % (UI_LIB, UI_BIN, BG_HOOK, BG_IMAGE, BG_IMAGE_IDLE,
               MODS_LOADER, TINT_HOOK, EWTRACE_HOOK, BITMAP_HOOK, MODS_LIST),
            timeout=20, retries=1)
        log("Removed the N3 vendor UI/background/mod files.")
    finally:
        try:
            stop_root(log)
        except Exception:
            pass
        adb_shell("sync; mount -o remount,ro /vendor", timeout=20)
        try:
            restore_stock(log)
            stop_root(log)
        except Exception as exc:  # noqa: BLE001
            log("USB restore warning: %s" % exc)
    return start_stock_ui(log)


# ------------------------------------------------------------------- status

def status() -> dict:
    st = {
        "usb": False,
        "dll": None,
        "dll_error": None,
        "root": False,
        "adb_path": find_adb(),
        "adb": [],
    }
    try:
        lib = L.Libusb0()
        st["dll"] = lib.path
        # libusb0's descriptor parse is unreliable here, but the device path is
        # always \\.\libusb0-...-0x2ca3-0x0020 -- the same match Duml.open uses.
        st["usb"] = any(
            ("0x%04x" % VID) in (d.get("filename") or "").lower()
            for d in lib.scan()
        )
    except Exception as exc:  # noqa: BLE001
        st["dll_error"] = str(exc)
    st["root"] = is_root()
    st["adb"] = adb_devices(st["adb_path"])
    return st


def open_terminal() -> None:
    """Open an interactive root shell in a new console window."""
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        cand = py[: -len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            py = cand
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([py, os.path.join(TOOLS, "root_shell.py")], creationflags=flags)


def self_test() -> int:
    print("N3 Control Deck self-test")
    print("  python :", sys.version.split()[0], sys.executable)
    print("  app dir :", APP_DIR)
    print("  tools   :", TOOLS)
    try:
        import crc_tables  # noqa: F401
        print("  crc     : embedded tables OK")
    except Exception as exc:  # noqa: BLE001
        print("  crc     : ERROR", exc)
    try:
        lib = L.Libusb0()
        devs = lib.scan()
        dji = [
            d for d in devs
            if ("0x%04x" % VID) in (d.get("filename") or "").lower()
        ]
        print("  libusb0 :", lib.path)
        print("  devices : %d, DJI %04x: %d" % (len(devs), VID, len(dji)))
    except Exception as exc:  # noqa: BLE001
        print("  libusb0 : ERROR", exc)
    print("  adb     :", find_adb() or "NOT FOUND")
    print("  adb dev :", adb_devices())
    print("  root    :", "up" if is_root() else "down")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
