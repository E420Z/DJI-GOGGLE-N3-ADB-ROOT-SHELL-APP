"""Host smoke test: imports and static checks, no device access."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)

import n3ctl            # noqa: E402
import mods as modman   # noqa: E402
import background       # noqa: E402
import theme_builder    # noqa: E402


def main() -> int:
    print("app:", APP)
    print("tools:", n3ctl.TOOLS)
    assert os.path.isdir(n3ctl.TOOLS), "tools dir missing"
    assert "Purple" in theme_builder.PRESETS, "Purple preset missing"
    assert "Menu only" in theme_builder.PRESETS, "Menu-only preset missing"

    plugins = os.path.join(APP, "plugins")
    found = 0
    for name in sorted(os.listdir(plugins)):
        pj = os.path.join(plugins, name, "plugin.json")
        if not os.path.exists(pj):
            continue
        data = json.load(open(pj, encoding="utf-8"))
        assert data.get("id") and data.get("name"), pj
        so = data.get("so")
        if so:
            assert os.path.exists(os.path.join(plugins, name, so)), so
        found += 1
        print("plugin:", data["id"], "ok")
    assert found >= 3, "expected plugins missing"

    stock = os.path.join(APP, "assets", "libew_gls_stock.so")
    print("stock lib:", "present" if os.path.exists(stock) else
          "missing (theme building disabled; add locally)")

    docs = os.path.join(ROOT, "docs")
    for name in ("SPARROW2.md", "SPARROW2-EVIDENCE.md", "RADIO-PROBE.md"):
        path = os.path.join(docs, name)
        assert os.path.exists(path), path
        text = open(path, encoding="utf-8", errors="replace").read()
        assert "Sparrow2" in text, name
    s2 = open(os.path.join(docs, "SPARROW2.md"), encoding="utf-8",
              errors="replace").read().lower()
    for needle in ("sdr_shell", "0x1e07", "-1002", "-1007", "amt",
                   "no exposed", "external"):
        assert needle in s2, "SPARROW2.md missing: %s" % needle
    print("sparrow2 docs: ok")

    print("smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
