# Goggles Stream: integration (4 edits, nothing else changes)

1. **HTML**: paste `goggles-stream.html` into `index.html` immediately after `</section>` of `#page-pcstream`.
2. **CSS**: in `<head>`, after `styles.css`, add `<link rel="stylesheet" href="goggles-stream.css">`.
3. **JS**: before `<script src="app.js"></script>`, add `<script src="goggles-stream.js"></script>`. It only defines `window.GogglesStream`.
4. **Nav**: after the PC Stream nav item, add
   `<button class="nav-item" data-go="gstream"><svg class="i"><use href="#i-camera"/></svg><span>Goggles Stream</span></button>`
5. **PAGES** (`app.js`): **append** at the end, so the Alt+1…7 mapping (`PAGES[n-1]`) doesn't shift:
   `{ id: "gstream", title: "Goggles Stream", group: "Device", icon: "camera", risk: "EXPERIMENTAL", subtitle: "1080p60 H.264 · goggles → this PC" },`
6. **Hooks** (`app.js`): in `onPageEnter(id)` add `if (id === "gstream") window.GogglesStream?.mount();`, and in
   `onPageLeave(id)` add `if (id === "gstream") window.GogglesStream?.unmount();`. Calling `mount()` again while mounted only refreshes.
7. **Backend**: expose `gstream_info()`, `gstream_start()` and `gstream_stop()` on the pywebview API. Without `window.pywebview` the page
   uses its own mock and never polls. `app.js`'s `createMock()` needs no changes.
8. **Optional**: `GogglesStream.update(info)` renders a pushed info object. It never starts a second poller, and it never starts playback unless mounted.
