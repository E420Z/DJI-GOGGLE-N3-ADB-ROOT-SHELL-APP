# N3 stock UI internals — first map

Date: 2026-11-26. Owner's device. Read-only static analysis of
`app/assets/libew_gls_stock.so` (fw 10.00.59.41) with **capstone 5.0.7** and
**pyelftools 0.33**.

Goal: learn the real UI so we can add/change things directly instead of
fighting runtime input hooks.

---

## 1. ELF layout

| Section | Address | File offset | Size |
|---|---:|---:|---:|
| `.rodata` | `0x379280` | `0x379280` | 93,723,644 |
| `.text` | `0x5dd9640` | `0x5dd8640` | 3,736,984 |
| `.data.rel.ro` | `0x6185738` | `0x6183738` | 1,554,232 |
| `.got` | `0x63010b0` | `0x62ff0b0` | 106,320 |
| `.data` | `0x63295b0` | `0x63265b0` | 260 |
| `.bss` | `0x63296b8` | — | 16,081 |

`.rodata` is the big EW resource blob (images/fonts/strings). Most menu labels
are **resource IDs**, not plain C strings.

---

## 2. The menu is Embedded Wizard C++ + resources

Key symbols (all in `.text` unless noted):

### Menu entrance / sidebar

```
DuMenuEntranceMenuEntrance__Init            0x5ffe250
DuMenuEntranceMenuEntrance_onTap            0x5ffe350
DuMenuEntranceMenuEntrance__ReInit          0x5ffe360
DuMenuEntranceMenuEntrance_UpdateViewState   0x5ffe3d0
DuMenuEntranceMenuEntranceLeft/Right/Top/Bottom
DuMenuEntranceMenuEntranceLayer__Init       0x5ffe930
DuMenuEntranceMenuEntranceLayer_popUpMainMenu 0x5ffec50
DuMenuEntranceMenuEntranceLayer_OnSetOnTapMenuEntranceTop 0x5fff030
```

The sidebar/layer is `DuMenuEntranceMenuEntranceLayer`; `popUpMainMenu` opens
the main menu through an EW manager.

### Entry actions (what a menu row does)

```
DuMenuItemsEntryActions__Init               0x5fffa40
DuMenuItemsEntryActions_StatusMenuEntryAction      0x601ef70
DuMenuItemsEntryActions_AppSettingsEntryAction     0x601f010
DuMenuItemsEntryActions_DebugUnitMenuEntryAction   0x601f060
DuMenuItemsEntryActions_GalleryPageEntryAction     0x601f100
DuMenuItemsEntryActions_FcCompassCalibratePageEntryAction  0x601f200
DuMenuItemsEntryActions_GlassesCompassCalibratePageEntryAction 0x601f2f0
DuMenuItemsEntryActions_FcImuCalibratePageEntryAction      0x601f390
DuMenuItemsEntryActions_GlassesImuCalibratePageEntryAction 0x601f480
DuMenuItemsEntryActions_GlsPlayBgVideoPageEntryAction      0x601f520
DuMenuItemsEntryActions_RcSettingsPageEntryAction          0x601f5c0
DuMenuItemsEntryActions_GimbalCalibratePageEntryAction     0x601f670
DuMenuItemsEntryActions_CameraToolBarEntryAction           0x601f6b0
DuMenuItemsEntryActions_FormatSdDialogEntryAction          0x601f6f0? (0x601f6d0)
DuMenuItemsEntryActions_StitchCalibrationPageEntryAction   0x601f740
DuMenuItemsEntryActions_VirtualLvRollCalibrationEntryAction 0x6021410
DuMenuItemsEntryActions_PcOtgEntryAction                   0x6021880
DuMenuItemsEntryActions_MobileOtgEntryAction               0x60218f0
DuMenuItemsEntryActions_AuthenticationEntryAction          0x6021960
DuMenuItemsEntryActions_WifiSinkEntryAction                0x60231b0
DuMenuItemsEntryActions_SimulatorEntryAction               0x6023260
DuMenuItemsEntryActions_DLNAEntryAction                    0x60232e0
DuMenuItemsEntryActions_NoviceEntryAction                  0x60233e0
DuMenuItemsEntryActions_McTutorialEntryAction              0x6023410
DuMenuItemsEntryActions_SafetyFrameConfigEntryAction       0x6023f00
DuMenuItemsEntryActions_McModePageEntryAction              0x60244a0
DuMenuItemsEntryActions_McManualConfigPageEntryAction      0x6024580
DuMenuItemsEntryActions_McCalibratePageEntryAction         0x6024690
DuMenuItemsEntryActions_enterBgVideoPage                   0x60249a0
DuMenuItemsEntryActions_BeginnerModePromptAction           0x6024a80
...
```

### Setting actions (non-page actions)

```
DuMenuItemsSettingActions__Init             0x5fffaa0
DuMenuItemsSettingActions_ResetFactoryAction        0x6021d00
DuMenuItemsSettingActions_ProductSwitchAction       0x6021ea0
DuMenuItemsSettingActions_ExitAudienceAction        0x6022740
DuMenuItemsSettingActions_TriggerRelay              0x6022790
DuMenuItemsSettingActions_LTEDebugInfoAction        0x60227e0
DuMenuItemsSettingActions_TriggerScriptNo1Action    0x6023020
DuMenuItemsSettingActions_TriggerScriptNo2Action    0x6023070
DuMenuItemsSettingActions_TriggerScriptNo3Action    0x60230c0
DuMenuItemsSettingActions_TriggerScriptNo4Action    0x6023110
DuMenuItemsSettingActions_TriggerScriptNo5Action    0x6023160
DuMenuItemsSettingActions_triggerResetCameraPara    0x6024e40
DuMenuItemsSettingActions_triggerResetFactory       0x6024e90
DuMenuItemsSettingActions_triggerProductSwitch      0x6024f20
DuMenuItemsSettingActions_triggerSyncUAVStorage     0x6024f90
```

### Menu model / views

```
MxMenuDefinitionMenu__Init                   0x6133ac0
MxMenuDefinitionMenuTree
MxMenuDefinitionMenuItem
MxMenuDefinitionItemCollection_actionIndexedImage 0x6136790
MxBindableMenu_* / MxBindableMenuItem_*
ViewsMenu* / ViewsMenuItem*
```

### String resources

`DuStringsfpv_*` symbols are 24-byte descriptors in `.data.rel.ro`
(e.g. `DuStringsfpv_setting_catalogue_camera_parameters_eis_hb_list` at
`0x62a8d40`). Example bytes:

```
0000000000000000 0400000000000000 0000000000000000
```

The text is **not** stored inline; it is an EW string-resource ID resolved at
runtime. There is no simple `.rodata` label table to edit.

---

## 3. What the disassembly shows

`DuMenuItemsEntryActions_GalleryPageEntryAction` gets an EW manager, checks a
member, creates a page object and pops it. `TriggerScriptNo1..5` call a common
EW routine `0x6177420` with script index 1..5. `AppSettingsEntryAction` calls
`0x6178300` with `w1=2`.

Important: a scan of `.rela.dyn` (288,539 entries) found **no relocation whose
addend is any of the menu action functions**. So the menu does not reference
actions through a simple pointer table we can retarget in the file; the
actions are direct C++ calls or registered at runtime.

There are also **no libc imports** for `system`, `popen`, `open`, `write`,
`close`, `fork`, or `execve` (only `dlopen`/`dlsym` appear). A static action
patch would have to use `dlopen`/`dlsym` or an EW/DIOS wrapper, not a convenient
`system()` call.

---

## 4. Feasible static paths (future work)

1. **Repurpose one entry action.** Overwrite a rarely used action function
   (e.g. `DebugUnitMenuEntryAction` or `TriggerScriptNo5Action`) with a code
   cave that opens the N3 overlay. This is a static lib patch, no runtime input
   hooks. It changes one existing stock row; the label remains until we can
   patch its resource ID.
2. **Add a real menu row.** Reverse `DuMenuItemsEntryActions__Init` / the
   `MxMenuDefinition` item collection and append an item + action. More work,
   but the clean end state.
3. **EW script trigger.** If `TriggerScriptNo1..5` are backed by file scripts
   or an EW script resource, replacing that resource with our action would be
   the smallest patch. Not confirmed yet.

None of these is a five-minute change; they are the next research phase.

---

## 5. Physical controls (from the input logger)

Measured on this unit:

| Control | Event |
|---|---|
| 5-way **up** | `event3` code **103** (`KEY_UP`) |
| 5-way **down** | `event3` code **108** (`KEY_DOWN`) |
| 5-way **left** | `event3` code **105** (`KEY_LEFT`) |
| 5-way **right** | `event3` code **106** (`KEY_RIGHT`) |
| 5-way **center** | `event0` code **28** (`KEY_ENTER`) |
| **Back** | `event0` code **158** (`KEY_BACK`) |
| **Power** | **no input event** (PMIC/OMC, not `/dev/input`) |

The stock left sidebar opens on a **long center** press (EW key 1), which is why
the long-center toggle conflicted with it.

## 6. Working gesture (interim)

- **Long-press 5-way UP** → open/close the N3 overlay.
- **Short up/down** → move selection.
- **Center** → select / open page.
- **Back** → back / close.

This avoids the power button (not an input key) and the long-center stock
sidebar. Verified with synthetic events; long-press up toggles the overlay with
the UI process staying alive.

---

## 7. Next steps

1. Reverse `DuMenuItemsEntryActions__Init` and the `MxMenuDefinition` item
   collection to find where rows/actions are registered.
2. Identify a safe action function/code cave and a writable string slot for a
   static "open N3 menu" stub.
3. Build a patched `libew_gls.so` via the theme builder, install, and test with
   Recover stock UI ready.
4. Then add a visible stock row (label + action) rather than repurposing one.

### Album/Gallery caveat (2026-11-26)

The Gallery action was patched as a static launcher, but the stock UI **greys
out Album when no SD card is inserted**, so its action never runs. That route is
inert; the real target must be a visible entry or a real added row.

---

## 8. UI launch chain (2026-11-26)

This is the important discovery: the stock UI is not one binary. It is a
**generic host loader + a UI library**.

`/vendor/dji_glasses_patched` (from `dji_glasses_vendor`) is the host. Its
`gs_start` (`0x3b0f0`) does:

```
dlopen("/vendor/libew_gls.so")
dlsym("ew_gui_start")              -> ctx+0x70
dlsym("ew_gui_stop")               -> ctx+0x78
dlsym("ew_gui_enable_key_event")   -> ctx+0x80
dlsym("ew_gui_disable_key_event")  -> ctx+0x88
build a 0x2298-byte context (0x256f0), set callbacks at +0x50/+0x60
call ew_gui_start(ctx)
```

The stock `libew_gls.so` implements the UI entry:

```
ew_gui_start        0x5dd9de0  (992 bytes)
ew_gui_stop         0x5dda530
ew_gui_enable_key_event  0x5dda5c0
ew_gui_disable_key_event 0x5dda600
ew_gui_init_pushes  0x5ddac30  (10,400 bytes)
ew_gui_deinit_pushes 0x5ddd4d0
EwBspKeyEventProcess 0x6168b70
EwBspTouchEventProcess 0x6168c90
```

`ew_gui_start` sequence (from imports):

```
duss_osal_mutex_create
property_get ×3 / strcasecmp        (display/mode config)
EwGuiBspInitFromFile
EwRegisterGlobalConfig
DjiGuiMwAdapterInit
EwGuiInit
EwGuiRegisterKeyHandler
EwGuiRegisterMwInitHandler
EwGuiRegisterMwMsgHandler
DjiGuiMwDeviceAutoObjectInit
DjiGuiMwStreamInit
DjiGuiMwTaskInit
EwGuiRun
ew_gui_init_pushes
```

`ew_gui_stop`: `EwGuiStop`, mutex destroy, `ew_gui_deinit_pushes`, image loader
stop/destroy. `ew_gui_enable/disable_key_event`: `EwBspEnableKeyInput`.

### Consequence: replace the UI library

The host is generic. A custom `/vendor/libew_gls.so` can export the same four
`ew_gui_*` symbols, ignore EW entirely, and run **our own full-screen UI** using
the host's display/input context (or `duss_hal_display_*` + `/dev/input`).

That is the clean path to “our own UI”:

- no EW menu model, no overlay window, no input-suppression hooks;
- our own page/tab stack and input mapping;
- recovery is simply restoring the stock `libew_gls.so`.

Open items before writing the shim:

1. Reverse the 0x2298-byte context from `0x256f0` (and callbacks `0x3a0ce0`,
   `0x3b030`) to find the display/input entry points.
2. Confirm the `ew_gui_start(ctx)` signature and return/semaphore expectations.
3. Implement a minimal shim that draws a test frame and reads input.
4. Then build the real pages/tabs.

---

## 9. Native stock-menu row (works, 2026-11-26)

Toolya itself does not contain a UI; the custom menu comes from the
**natartos `menu` mod** (installed through Toolya). Its source is in
`natartos-src/mods/menu/mod.c` and its method is:

1. Patch the menu's `Reload` slot.
2. On each menu open, clone the last stock item and call
   `MxBindableAbstractMenu_AddItemFromData`.
3. Re-layout with `CoreVerticalList_OnSetNoOfItems` + `Postreload`.

On the N3 the same primitives exist, but the details differ:

### Real vtables

`__vmt_DuThemedControlsMainMenu` / `__vmt_DuThemedControlsMoreMenu` are
**class descriptors**, not object vtables. The real vtable pointers are GOT
slots loaded by the `__Init` functions:

```
0x6316bf0  -> DuThemedControlsMainMenu  (stock left sidebar)
0x6319460  -> DuThemedControlsMoreMenu
```

The GOT slots are valid as soon as the library is mapped; the method slots
inside the vtable are filled at EW init time, so patch from a delayed thread.

### N3 slot map (from `MxBindableAbstractMenu_Reload`)

```
55  Reload        (ldr [vmt,#0x1b8] in __Reload)
56  RemoveItems   (0x1c0)
59  Prereload     (0x1d8)
60  Postreload    (0x1e0)
62  AddItem       (0x1f0)
data source: 11 = Size   (0x58)   12 = At (0x60)
```

### Adding a visible row

The simplest stable result is to replace the disabled **Album** entry
(index 1), not append. Clone an always-enabled stock item (Settings, index 3),
then replace:

```
d[4]  = action object (64-byte clone, [4]=object, [5]=method)
d[5]  = stock ResourcesBitmap icon (or a custom one)
d[16] = title XString (EwNewStringAnsi("N3"))
d[17] = subtitle XString
d[18] = type (keep the template's type)
```

…and return that item from the data source's `At(1)`.

### Important: copy the data-source vtable

The data-source vtable is **shared** by other menus. Patching its `Size`/`At`
slots directly also hits the camera-parameter toolbar and crashes in
`EwCompString` (`MxBindableMenuItem_OnSetCaption`). Give the target data source
its own vtable copy and point only that object at it.

### Result

- Left sidebar: Status, **N3**, Transmission, Settings
- No input hooks, no overlay, no frame compositing
- `/vendor/libew_gls.so` is not modified; reboot restores Album
- Implementation: `mods/menuinject/mod.c`
- Loader aliases: `__n3_main_menu_vmt`, `__n3_more_menu_vmt`
  (`modloader/n3mods.c`)
- Deploy/test: `app/tools/deploy_menu_inject.py`

### Native E420Z page (same menu control)

The stock sidebar is reused as the E420Z page.  The data source has two
modes:

```
mode 0: E420Z (new) + all original stock rows
mode 1: STATUS / SDR SCAN / DISPLAY TEST / ABOUT / BACK
```

Pressing E420Z sets mode 1 and calls the stock `Reload`; BACK sets mode 0.
EW strings for the submenu are recreated in the same frame as the reload
(the previous frame's strings are garbage-collected; using them panics in
`EwCompString`).  The Dismiss slot resets mode 0 so the next open is stock.

No overlay window and no input hooks are needed for this page.

### Icon / layout limits (open)

- `EwCreateBitmap` + `ResourcesBitmap` on this N3 build accepts the bitmap
  but the menu renders it blank; cloning the stock wrapper also renders
  blank.  `EwLoadBitmap(path)` panics when given a filesystem path.
- The stock theme chooses the row glyph from the item's action/type, so a
  custom action gets the default glyph.  The E420Z row currently uses the
  stock hexagon glyph as the closest match to the E420Z logo.
- Changing `CoreVerticalList` item height (field +0x150 / `OnSetItemHeight`)
  stores the value but the following reload panics.  Five rows therefore
  need a theme-level layout patch; the stock four-row layout is kept for
  stability.
