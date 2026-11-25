# Plugins

Drop a folder here with a `plugin.json` to add a mod or command plugin. The app
scans this folder on **Mods → Refresh**. Folders starting with `_` are ignored.

## Minimal command plugin

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0",
  "type": "command",
  "description": "What it does.",
  "risk": "low",
  "install": ["echo hi > /data/local/tmp/my_plugin.txt"],
  "uninstall": ["rm -f /data/local/tmp/my_plugin.txt"]
}
```

`install` / `uninstall` commands run as uid 0 in the `dji_services` domain while
`/vendor` is temporarily read-write.

## .so mod

A Natartos-style mod is an LD_PRELOAD shared object. Put it in `files/` and use:

```json
{
  "id": "my-mod",
  "name": "My Mod",
  "version": "1.0",
  "type": "hook",
  "description": "What it hooks.",
  "risk": "medium",
  "so": "files/my_mod.so",
  "filename": "n3_my_mod.so",
  "requires": [],
  "experimental": false,
  "install": [],
  "uninstall": []
}
```

The app pushes it to `/vendor/n3_my_mod.so`, adds it to the loader list
(`/data/local/tmp/n3mods.list`) and restarts the UI with `n3mods.so`.

Optional extra files:

```json
"files": [
  { "src": "files/icon.rgba", "dst": "/vendor/icon.rgba", "mode": "644" },
  { "src": "files/data.bin", "dst": "/data/local/tmp/data.bin", "mode": "644" }
]
```

The `mode` field accepts an octal string (`"755"`) or an integer.
