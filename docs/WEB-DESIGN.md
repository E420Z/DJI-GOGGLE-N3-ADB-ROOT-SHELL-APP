# N3 ROOT — UI design notes

Static front-end for the pywebview (WebView2) shell. Plain HTML/CSS/JS, no build
step, no network. Open `index.html` directly; add `?mock=1` to force mock data.

## Files

| File | Role |
| --- | --- |
| `index.html` | App shell, inline SVG icon sprite, all seven pages, palette, modal |
| `styles.css` | Tokens → base → layout → components → pages → overlays → motion |
| `app.js` | Navigation, backend bridge, mock backend, palette, toasts, modals |

## Visual system

- **Canvas** `#08060D`, two accent-tinted radial glows plus an SVG-noise grain layer (4.5% opacity).
- **Surfaces** are translucent gradient cards with a 1px `rgba(255,255,255,.07)` border, an 18px radius and
  a hairline top highlight. Only the sidebar, topbar, overlays and toasts use `backdrop-filter`, which keeps
  scrolling cheap.
- **Accent** comes from `--accent` / `--accent-rgb`. Settings can switch it to purple, cyan, amber or rose, and
  glows, focus rings, the nav pill and primary buttons follow.
- **Safety colours** are fixed and only ever mean risk: SAFE `#4ADE80`, EXPERIMENTAL `#FBBF24`, RISKY `#F87171`.
  The same badge, tile tint, button tone and modal styling are used everywhere.
- **Type**: Segoe UI Variable Display for headings (tight negative tracking), Text for 13.5px body,
  Cascadia Mono for consoles, serials and resolutions. Labels are 10.5px uppercase with .14em tracking.
- **Spacing**: 4px scale. Density "compact" only rewrites `--pad`, `--gap`, `--ctl-h` and `--content-x`.
- **Icons**: one `<symbol>` sprite on a 24px grid, 1.75 stroke, rendered at 18px (16px inside buttons).

## Motion

The page fades in and slides up 10px, and its cards follow at a 45ms stagger. The nav pill slides on a spring.
Live status dots pulse with a ping ring and sit static and dim when offline. Cards lift 3px and their border
glows in the card's risk tint. Buttons scale to .965 when pressed. Metrics count up with an ease-out cubic.
Toasts spring in from the bottom right and show a progress bar that pauses on hover. The palette and modals
scale and fade over a blurred backdrop. Skeleton shimmer and inline spinners cover async work. When the live
preview has no frame it shows a scanline field with a sweeping band, and frames are double-buffered with
`img.decode()` so swaps never flash.

Settings → Motion off adds `.reduce-motion` to `<html>`. That collapses every animation and transition to 1ms
and removes the decorative loops. The OS `prefers-reduced-motion` setting is honoured too.

## Behaviour

- **Backend**: uses `window.pywebview.api` once ready (`pywebviewready`). Without a host it falls back after
  1.5s to a deterministic mock, which a MOCK chip and a sidebar note make obvious.
- **Calls**: every call goes through `call()`, which handles busy state on all matching buttons, a WEB log
  entry, the toast, and a follow-up `status()` refresh. Status polls every 5s and logs every 3s, but only while
  Logs is open. Live frames are pulled only while E420Z is visible.
- **Confirmations**: EXPERIMENTAL and RISKY actions ask through a custom modal. For risky prompts, focus starts
  on Cancel so Enter never confirms by accident. The root shell asks once per session and never auto-runs. Quick
  commands only fill the prompt.
- **Logs tabs**: NATARTOS, N3MODS, UI and CAPTURE come from `logs()`. WEB is the in-memory log of this UI's own
  API calls. Clear is client-side only.
- **Keyboard**: `Ctrl/Cmd+K` palette, `Alt+1…7` pages, `Ctrl+R`/`F5` refresh status, `Esc` closes overlays,
  arrows move through log tabs and palette results, `↑/↓` walks shell history.
- **Responsive**: designed at 1360×880, with grids built on `minmax(0, 1fr)` and breakpoints at 1320/1240px so 1120×720 has no horizontal scroll. Below 1040px the
  sidebar collapses to icons for browser previews.
