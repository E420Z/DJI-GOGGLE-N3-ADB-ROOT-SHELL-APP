# N3 stock-UI SDK (runtime menu hooks)

This is the practical SDK for adding native rows and opening stock panels on the
DJI Goggles N3.  It is built from the proven `mods/menuinject` implementation,
not a separate abstraction layer yet.

Reference implementation: `mods/menuinject/mod.c`
Loader: `modloader/n3mods.c` (exports `__n3_main_menu_vmt` /
`__n3_more_menu_vmt` and starts the late vtable patch thread)
Build: `mods/menuinject/build.py` (zig cc, aarch64)
Deploy: `app/tools/deploy_menu_inject.py`

---

## 1. What the loader gives you

`/vendor/n3mods.so` is an `LD_PRELOAD` loader.  It:

- reads `/data/local/tmp/n3mods.list` (one `/vendor/*.so` per line)
- `dlopen`s each mod with `RTLD_GLOBAL`
- calls `natartos_mod_init(loader_dlsym)` and `natartos_mod_register(...)`
- resolves the real object vtables and exposes them as:

```
__n3_main_menu_vmt   -> DuThemedControlsMainMenu object vtable
__n3_more_menu_vmt   -> DuThemedControlsMoreMenu object vtable
```

`loader_dlsym(RTLD_DEFAULT, ...)` falls back to the EW runtime and the display
library, so `EwNewStringAnsi`, `CoreVerticalList_*`, etc. are available.

The `__vmt_*` symbols in `libew_gls.so` are **class descriptors**, not object
vtables.  Always use the loader aliases.

---

## 2. Slot map

`MxBindableAbstractMenu`:

```
55  Reload        (0x1b8)
56  RemoveItems   (0x1c0)
57  Dismiss       (0x1c8)
59  Prereload     (0x1d8)
60  Postreload    (0x1e0)
62  AddItem       (0x1f0)
```

Data source (`self[73]` / `self+0x248`):

```
11  Size   (0x58)
12  At     (0x60)
```

Patch `Reload` (and `Dismiss` if you need a cleanup hook) from the loader's
late thread, after EW has filled the slots.

---

## 3. Add a row to the left sidebar

1. In the Reload hook, find `ds = ((unsigned long*)self)[73]`.
2. Give **that object** a private vtable copy; never patch the shared class
   vtable (it also hits the camera toolbar and crashes).
3. Override `Size` and `At`:

```c
static int wrap_size(void *ds) {
    if (ds == g_ds) return g_orig_size(ds) + 1;   // new row + stock rows
    return g_orig_size(ds);
}
static void *wrap_at(void *ds, int i) {
    if (ds == g_ds) {
        if (i == 0) return g_item;                // your row first
        return g_orig_at(ds, i - 1);              // shift stock rows
    }
    return g_orig_at(ds, i);
}
```

4. Build your item from a stock template (`g_orig_at(ds, templateIndex)`):

```
item[4]  = action object (64-byte clone; [4]=slot_obj, [5]=slot_fn)
item[5]  = icon (stock ResourcesBitmap)
item[16] = title XString
item[17] = subtitle XString
item[18] = template type
```

5. Recreate the title with `EwNewStringAnsi` **in the same Reload frame**.
   Strings from a previous frame are garbage-collected and panic in
   `EwCompString`.
6. Let the stock `Reload` build the list, then call
   `CoreVerticalList_OnSetNoOfItems(self, 0)` and the Postreload slot once to
   force a rebuild when the stock UI reuses cached views.

---

## 4. Actions

The stock dispatcher calls `slot_fn(slot_obj)`.  To run your own code:

```c
static void my_action(void *obj) { /* ... */ }

((unsigned long*)act)[4] = (unsigned long)ctx;      // passed as obj
((unsigned long*)act)[5] = (unsigned long)my_action;
```

To reuse a stock action (this is how E420Z opens the Settings panel):

```c
void *stock_item = g_orig_at(ds, 3);          // Settings row
unsigned long *ip = stock_item;
unsigned long *a  = (unsigned long*)ip[4];    // action object
void *slot_obj = (void*)a[4];
void *slot_fn  = (void*)a[5];                 // call slot_fn(slot_obj, ...)
```

This works without knowing the action’s symbol name, and it respects the
runtime binding.

---

## 5. Opening a stock panel (the big box)

Capturing the Settings row’s action and calling `slot_fn(slot_obj, ...)` opens
the stock Settings-style content panel beside the sidebar.  This is what
`menu_action` in `mods/menuinject/mod.c` does.

The stock Settings panel is a **static EW page** (Safety / Control / Camera /
Display / About).  Its rows are not a simple data source, so replacing their
labels with custom rows requires cloning the static page objects (next step).
The stock rows themselves work.

### Stock-styled panel template

For a custom content panel that matches the stock layout, use
`sdk/ui_template/mod.c`:

- window: `x=360, y=85, w=670, h=910` (the stock Settings panel area)
- dark neutral surfaces, purple selection bar, centered title
- rows drawn in `on_tick`, actions in `on_key` / `on_swipe`
- open it from a native row by touching `/data/local/tmp/n3_app_on`
- `n3app` reads event3 directions and event0 center/Back; the CoreRoot hook
  suppresses stock input while the panel is open

Build it with `sdk/build.ps1` and load it alongside `n3menuinject.so`
(`/data/local/tmp/n3mods.list`).

`N3_MAX_W/H` in `sdk/n3app.c` is now 1200x960 so the panel can fill the
big-box area.

### Input caveat (N3, 2026-11-26)

- 5-way up/down arrive on `event3` as 103/108 and are delivered as
  `on_swipe(0, +100)` / `on_swipe(0, -100)`.  Map **physical down to the next
  row** (the physical down code is 103 on this unit).
- CoreRoot delivers **center as key 1** and **Back as key 2** on this build,
  not 6/19.  Map key 1 → ENTER and key 2 → BACK while the panel is active.
- Key `4` is **UP** here, not right.  Never map it to “select”.
- Center/Back can also be driven by the stock action signal:
  `/data/local/tmp/n3_panel_enter` (n3app converts it to ENTER) if the stock
  focus is still on the E420Z row.
- Touchpad tap (`on_tap`) is the fallback if the stock focus is lost.

---

## 6. Known limits (2026-11-26)

- **Custom bitmap icons**: `EwCreateBitmap` + `ResourcesBitmap` renders blank on
  this N3 build; cloning the stock wrapper also renders blank.  Use a stock
  icon for now.  The E420Z logo asset is in `mods/menuinject/icon.png` /
  `icon.h` for the future.
- **Item height**: writing `self+0x150` / `CoreVerticalList_OnSetItemHeight`
  stores the value but the next reload panics.  Five visible rows require a
  theme-level layout patch.
- **Static pages**: the Settings panel rows are static EW objects; custom labels
  need page-object cloning, not a data-source swap.
- **Dismiss**: reset any mode flags in the Dismiss hook so the next menu open is
  stock.

---

## 7. Build & deploy

```powershell
# build the mod
py -3.12 mods\menuinject\build.py

# deploy and restart the UI
py -3.12 app\tools\deploy_menu_inject.py

# enable the row (opt-in flag)
adb shell touch /data/local/tmp/n3menuinject_on

# logs
adb shell tail -40 /data/local/tmp/natartos.log
```

Recovery: `Recover stock UI` in the PC app, or reboot.  Nothing in
`/vendor/libew_gls.so` is modified.

---

## 8. Minimal mod skeleton

```c
#define NTLOG_PREFIX "myui"
#include "natartos_common.h"

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = loader_dlsym;
    // resolve EW APIs, then install the Reload hook from the late thread
    return 1;
}

int n3_menu_late_init(void) {
    void *vmt = g_dlsym(RTLD_DEFAULT, "__n3_main_menu_vmt");
    // patch vmt[55] with hook_reload (see mods/menuinject/mod.c)
    return 1;
}
```

Copy the proven helpers from `mods/menuinject/mod.c`: `patch_slot`,
`patch_ds`, `wrap_size/wrap_at`, `prepare_item`, `hook_reload`.
