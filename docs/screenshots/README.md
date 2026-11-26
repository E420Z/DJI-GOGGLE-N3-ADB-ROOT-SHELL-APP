# Screenshots

## Desktop app (pywebview + HTML/CSS/JS)

| File | What |
|---|---|
| `web_connection.png` | Connection page: USB / root / ADB cards, device summary, first-run checklist. |
| `web_e420z.png` | E420Z live preview with the backend's real scale list and the capture panel. |
| `web_sparrow2.png` | Sparrow2 read-only page: report, tool inventory, console help, doc links. |
| `web_root_shell.png` | Root Shell with the `/system` block banner and quick read-only commands. |
| `web_mods.png` | Mods & UI cards with SAFE / EXPERIMENTAL / RISKY badges. |
| `web_logs.png` | Logs with NATARTOS / N3MODS / UI / CAPTURE / WEB tabs. |
| `web_settings.png` | Preferences, theme picker, safety key and the DANGER card. |

These are headless Edge captures (the same Chromium engine WebView2 uses) of
the static UI in mock mode, so every shot carries the **MOCK** chip. The goggles
were not connected when they were taken; the layout, colours and motion are the
real thing. `docs/screenshot.png` (README hero) is a crop of the Connection
page.

Reproduce with:

```powershell
powershell -File app/tools/ui_shot.ps1 -Page connection
```

## Goggles UI (dmabuf captures)

| File | What |
|---|---|
| `e420z_sidebar.png` | Stock left sidebar with the new **E420Z** row (native injection). |
| `e420z_panel.png` | E420Z opens the stock-styled content panel beside the sidebar. |
| `e420z_panel_list.png` | Panel list with **BAND SCAN** selected after 5-way down. |
| `e420z_status.png` | STATUS detail page in the panel. |
| `e420z_band_scan.png` | BAND SCAN detail page (simulated, read-only). |

These are dmabuf captures from the owner's N3 at 1920x1080. The panel is drawn
in the same area as the stock Settings panel and reuses the native sidebar
renderer; the detail pages are read-only.
