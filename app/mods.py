"""mods.py - Natartos-style mod manager for the N3 root app.

Mods are LD_PRELOAD shared objects (or command-only plugins).  Because the N3
cannot create /vendor/natartos/mods, everything is flat in /vendor and a small
loader (n3mods.so) reads /data/local/tmp/n3mods.list.

Built-ins are the adapted Natartos mods in assets/mods.  Drop new plugins in
plugins/<id>/plugin.json; they are picked up automatically.
"""
from __future__ import annotations

import json
import os
import time

import n3ctl

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP_DIR, "assets", "mods")
PLUGINS = os.path.join(APP_DIR, "plugins")
STATE_DIR = os.path.join(APP_DIR, "state")
STATE = os.path.join(STATE_DIR, "mods.json")

BUILTINS = [
    {
        "id": "background",
        "name": "Custom Background",
        "version": "2.0-n3",
        "type": "theme",
        "description": "Replaces the cycling DJI backgrounds with your own "
                       "1920x1080 JPEG. Managed from the Background tab.",
        "risk": "low",
        "managed": "background",
        "experimental": False,
    },
    {
        "id": "menu",
        "name": "Menu Framework",
        "version": "3.0-n3",
        "type": "menu",
        "description": "Natartos menu injector, adapted to the N3 MoreMenu "
                       "vtable. Experimental until the vtable patch is tested.",
        "risk": "high",
        "so": "hook_menu.so",
        "files": ["hook_menu.so"],
        "experimental": True,
    },
    {
        "id": "popen",
        "name": "Script Redirect",
        "version": "5.0-n3",
        "type": "hook",
        "description": "Redirects popen(./bin/debug_script_*) to "
                       "/data/local/tmp/. Used by Doom/Stream style apps.",
        "risk": "medium",
        "so": "hook_popen.so",
        "files": ["hook_popen.so"],
        "experimental": True,
    },
    {
        "id": "template",
        "name": "Sample Menu Item",
        "version": "1.0",
        "type": "menu-item",
        "description": "Registers a harmless 'Template' item that toggles "
                       "/data/local/tmp/natartos_template.",
        "risk": "low",
        "so": "mod_template.so",
        "files": ["mod_template.so"],
        "requires": ["menu"],
        "experimental": True,
    },
]


def _load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            s = json.load(f)
        if "installed" not in s:
            s["installed"] = {}
        return s
    except Exception:
        return {"installed": {}}


def _save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _norm_builtin(m):
    out = dict(m)
    out["source"] = "built-in"
    out["source_dir"] = ASSETS
    primary = m.get("so")
    out["so_src"] = os.path.join(ASSETS, primary) if primary else None
    out["so_dst"] = "/vendor/" + primary if primary else None
    out["files"] = [
        (os.path.join(ASSETS, f), "/vendor/" + f,
         0o755 if f.endswith(".so") else 0o644)
        for f in m.get("files", []) if f != primary
    ]
    out.setdefault("requires", [])
    out.setdefault("install", [])
    out.setdefault("uninstall", [])
    return out


def _norm_plugin(path, m):
    out = dict(m)
    out["source"] = "user"
    out["source_dir"] = path
    so = m.get("so")
    if so:
        out["so_src"] = os.path.join(path, so)
        out["so_dst"] = "/vendor/" + (m.get("filename") or os.path.basename(so))
    else:
        out["so_src"] = None
        out["so_dst"] = None
    files = []
    for f in m.get("files", []):
        src = os.path.join(path, f["src"])
        dst = f.get("dst") or ("/vendor/" + os.path.basename(f["src"]))
        files.append((src, dst, int(f.get("mode", "644"), 8)
                      if isinstance(f.get("mode"), str) else f.get("mode", 644)))
    out["files"] = files
    out.setdefault("requires", [])
    out.setdefault("install", [])
    out.setdefault("uninstall", [])
    out.setdefault("risk", "medium")
    out.setdefault("experimental", False)
    return out


def refresh():
    """Return built-in + user mods with their installed state."""
    state = _load_state()
    installed = state["installed"]
    bg = n3ctl.ui_state().get("background", False)
    mods = [_norm_builtin(dict(m)) for m in BUILTINS]
    if os.path.isdir(PLUGINS):
        for name in sorted(os.listdir(PLUGINS)):
            if name.startswith("_"):
                continue
            d = os.path.join(PLUGINS, name)
            j = _read_json(os.path.join(d, "plugin.json"))
            if not j or not j.get("id") or not j.get("name"):
                continue
            mods.append(_norm_plugin(d, j))
    for m in mods:
        if m.get("managed") == "background":
            m["installed"] = bool(bg)
        else:
            m["installed"] = m["id"] in installed
    return mods


def find(mod_id):
    for m in refresh():
        if m["id"] == mod_id:
            return m
    return None


def mods_for_ui():
    """Ordered /vendor .so paths for the loader list (menu first)."""
    state = _load_state()
    recs = [r for r in state["installed"].values() if r.get("so")]
    recs.sort(key=lambda r: 0 if r.get("id") == "menu" else 1)
    return [r["so"] for r in recs]


def _push_mod_files(mod, log):
    seen = set()
    if mod["so_src"]:
        if not os.path.exists(mod["so_src"]):
            raise RuntimeError("missing mod file: " + mod["so_src"])
        n3ctl.push_file(mod["so_src"], mod["so_dst"], log=log)
        n3ctl.run_root("chmod 755 %s" % mod["so_dst"], timeout=6, retries=1)
        seen.add(mod["so_dst"])
    for src, dst, mode in mod["files"]:
        if dst in seen:
            continue
        if not os.path.exists(src):
            raise RuntimeError("missing plugin file: " + src)
        n3ctl.push_file(src, dst, log=log)
        n3ctl.run_root("chmod %o %s" % (mode, dst), timeout=6, retries=1)
        seen.add(dst)


def install(mod_id, log=print) -> bool:
    mod = find(mod_id)
    if not mod:
        raise RuntimeError("unknown mod: " + mod_id)
    if mod.get("managed") == "background":
        raise RuntimeError("Use the Background tab to install a custom image.")
    # install dependencies first
    for dep in mod.get("requires", []):
        if not find(dep) or not find(dep).get("installed"):
            log("Installing dependency: %s" % dep)
            install(dep, log=log)

    loader = os.path.join(ASSETS, "n3mods.so")
    try:
        with n3ctl.vendor_write(log):
            log("Stopping the UI before replacing mod files...")
            n3ctl.run_root(n3ctl.STOP_UI, timeout=15, retries=1)
            # Always refresh the loader; it is small and may have been updated.
            n3ctl.push_file(loader, n3ctl.MODS_LOADER, log=log)
            n3ctl.run_root("chmod 755 %s" % n3ctl.MODS_LOADER,
                           timeout=6, retries=1)
            _push_mod_files(mod, log)
            for cmd in mod.get("install", []):
                log("install: %s" % cmd)
                out = n3ctl.run_root(cmd, timeout=45, retries=1)
                if out:
                    log(out)
    except Exception:
        n3ctl.start_ui(log, mods=mods_for_ui())
        raise

    state = _load_state()
    state["installed"][mod["id"]] = {
        "id": mod["id"],
        "name": mod["name"],
        "version": mod.get("version", ""),
        "so": mod.get("so_dst") or "",
        "files": [dst for _src, dst, _mode in mod.get("files", [])],
        "installed_at": int(time.time()),
    }
    _save_state(state)
    log("Installed %s." % mod["name"])
    n3ctl.start_ui(log, mods=mods_for_ui())
    return True


def uninstall(mod_id, log=print) -> bool:
    mod = find(mod_id)
    if not mod:
        raise RuntimeError("unknown mod: " + mod_id)
    if mod.get("managed") == "background":
        raise RuntimeError("Use the Background tab to remove the image.")
    state = _load_state()
    rec = state["installed"].get(mod_id, {})
    try:
        with n3ctl.vendor_write(log):
            n3ctl.run_root(n3ctl.STOP_UI, timeout=15, retries=1)
            for cmd in mod.get("uninstall", []):
                log("uninstall: %s" % cmd)
                out = n3ctl.run_root(cmd, timeout=45, retries=1)
                if out:
                    log(out)
            targets = set(rec.get("files") or [])
            if rec.get("so"):
                targets.add(rec["so"])
            if mod.get("so_dst"):
                targets.add(mod["so_dst"])
            for dst in mod.get("files", []):
                targets.add(dst[1])
            if targets:
                n3ctl.run_root("rm -f " + " ".join(sorted(targets)),
                               timeout=15, retries=1)
                log("Removed: " + ", ".join(sorted(targets)))
    except Exception:
        n3ctl.start_ui(log, mods=mods_for_ui())
        raise

    state["installed"].pop(mod_id, None)
    _save_state(state)
    log("Uninstalled %s." % mod["name"])
    n3ctl.start_ui(log, mods=mods_for_ui())
    return True


def clear_installed():
    _save_state({"installed": {}})


def open_folder():
    os.makedirs(PLUGINS, exist_ok=True)
    os.startfile(PLUGINS)
