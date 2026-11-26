/*
 * menuinject — native N3 entry + native N3 submenu in the stock sidebar.
 *
 * The stock left sidebar is a DuThemedControlsMainMenu.  We give its data
 * source a private vtable and present two modes:
 *
 *   mode 0 (stock): original rows, with the disabled Album row replaced by
 *                   our "N3" row (index 1)
 *   mode 1 (N3):    our own native rows in the SAME stock menu control:
 *                   STATUS / SDR SCAN / DISPLAY TEST / ABOUT / BACK
 *
 * Pressing N3 calls the stock Reload with mode 1; BACK calls it with mode 0.
 * No overlay window, no input hooks, no page object creation.  The stock menu
 * renderer, focus, animation and input handling are used unchanged.
 *
 * N3 slot map (from MxBindableAbstractMenu_Reload):
 *   55 = Reload, 57 = Dismiss, 59 = Prereload, 60 = Postreload, 62 = AddItem
 * data source: 11 = Size, 12 = At
 *
 * Opt-in: create /data/local/tmp/n3menuinject_on.
 */
#define NTLOG_PREFIX "menuinject"
#include "natartos_common.h"
#include "icon.h"

#define MY_RTLD_NEXT ((void *)(long)-1)

#define RELOAD_SLOT     55
#define DISMISS_SLOT    57
#define POSTRELOAD_SLOT 60
#define DS_SIZE_SLOT    11
#define DS_AT_SLOT      12

/* The visible left sidebar: Status, Album, Transmission, Settings.
 * Album is index 1 and is disabled without an SD card, so it is repurposed.
 * Settings (index 3) is always enabled and is our visual template. */
#define REPLACE_INDEX   0
#define TEMPLATE_INDEX  0

#define SUB_COUNT 5
static const char *SUB_TITLES[SUB_COUNT] = {
    "STATUS", "SDR SCAN", "DISPLAY TEST", "ABOUT", "BACK"
};

#define FLAG_INJECT "/data/local/tmp/n3menuinject_on"

typedef void (*reload_fn)(void *self);
typedef void *(*new_str_fn)(const char *ascii);
typedef void (*set_noi_fn)(void *self, int n);
typedef void (*set_h_fn)(void *self, int h);
typedef int (*pthread_create_fn)(unsigned long *, const void *,
                                 void *(*)(void *), void *);
typedef int (*count_fn)(void *datasource);
typedef void *(*get_item_fn)(void *datasource, int index);

static void *(*g_loader_dlsym)(void *, const char *) = 0;
static void *g_vmt_main = 0;
static void *g_vmt_more = 0;
static void *g_reload_impl = 0;
static void *g_dismiss_impl = 0;
static void *g_dismiss_more_impl = 0;
static void *g_menu_self = 0;
static new_str_fn g_new_str = 0;
static set_noi_fn g_set_noi = 0;
static set_h_fn g_set_h = 0;
static int g_orig_h = 0;

static int g_patched_main = 0;
static int g_patched_more = 0;

static int g_mode = 0;                 /* 0 = stock rows, 1 = N3 rows */
static int g_sub_ready = 0;

/* Data-source wrapper state.  A private vtable copy keeps unrelated menus
 * (camera toolbar etc.) untouched. */
static void *g_ds = 0;
static count_fn g_orig_size = 0;
static get_item_fn g_orig_at = 0;
static int g_ds_patched = 0;
static void *g_ds_vmt[32];

static unsigned char g_item[256] __attribute__((aligned(8)));
static unsigned char g_act[64] __attribute__((aligned(8)));
static int g_item_ready = 0;

/* N3 submenu items. */
typedef struct { int idx; } sub_slot;
static sub_slot g_sub_slot[SUB_COUNT];
static unsigned char g_sub_item[SUB_COUNT][256] __attribute__((aligned(8)));
static unsigned char g_sub_act[SUB_COUNT][64] __attribute__((aligned(8)));
static void *g_sub_title[SUB_COUNT];

/* E420Z content page (stock Settings / MoreMenu panel). */
#define PAGE_COUNT 5
static const char *PAGE_TITLES[PAGE_COUNT] = {
    "STATUS", "BAND SCAN", "DISPLAY TEST", "ABOUT", "BACK"
};
static sub_slot g_page_slot[PAGE_COUNT];
static unsigned char g_page_item[PAGE_COUNT][256] __attribute__((aligned(8)));
static unsigned char g_page_act[PAGE_COUNT][64] __attribute__((aligned(8)));
static void *g_page_title[PAGE_COUNT];
static int g_page_ready = 0;
static int g_e420z_page = 0;

static void *g_ds_more = 0;
static count_fn g_orig_size_more = 0;
static get_item_fn g_orig_at_more = 0;
static void *g_ds_more_vmt[32];
static void *g_more_act_fn[8];
static void *g_more_act_obj[8];
static void *g_main_act_fn[8];
static void *g_main_act_obj[8];

/* ── custom N3 icon (EW ResourcesBitmap) ────────────────────────────────── */

typedef struct { int x, y; } XPoint;
typedef struct { int x1, y1, x2, y2; } XRect;
typedef void *(*create_bmp_fn)(int format, XPoint size, XPoint delay, int frames);
typedef void *(*lock_bmp_fn)(void *bmp, int frame, XRect area, int rd, int wr);
typedef void (*unlock_bmp_fn)(void *lock);
typedef void *(*new_obj_fn)(void *classVMT, int dummy);
typedef void (*res_init_fn)(void *bmp, void *raw);
typedef void *(*load_bmp_fn)(const char *path);
typedef void (*void_fn)(void);

static create_bmp_fn g_create_bmp = 0;
static lock_bmp_fn g_lock_bmp = 0;
static unlock_bmp_fn g_unlock_bmp = 0;
static new_obj_fn g_new_obj = 0;
static res_init_fn g_res_bmp_init = 0;
static load_bmp_fn g_load_bmp = 0;
static void *g_vmt_res_bmp = 0;
static void *g_n3_icon = 0;
static unsigned char g_icon_obj[128] __attribute__((aligned(8)));
static void_fn g_open_settings = 0;
static void *g_settings_obj = 0;
static void *g_settings_method = 0;

static void icon_rect(unsigned char *px, int pitchX, int pitchY, int w, int h,
                      int x0, int y0, int x1, int y1) {
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > w) x1 = w;
    if (y1 > h) y1 = h;
    for (int y = y0; y < y1; y++) {
        unsigned char *row = px + (long)y * pitchY;
        for (int x = x0; x < x1; x++) {
            unsigned char *p = row + (long)x * pitchX;
            p[0] = 255; p[1] = 255; p[2] = 255; p[3] = 255;
        }
    }
}

static void *make_n3_icon(void *stock) {
    if (!g_create_bmp || !g_lock_bmp || !g_unlock_bmp) return 0;
    const int W = E420Z_ICON_W, H = E420Z_ICON_H;
    XPoint sz; sz.x = W; sz.y = H;
    XPoint dl; dl.x = 0; dl.y = 0;
    void *raw = g_create_bmp(3, sz, dl, 1);
    if (!raw) return 0;

    XRect area; area.x1 = 0; area.y1 = 0; area.x2 = W; area.y2 = H;
    unsigned char *lk = (unsigned char *)g_lock_bmp(raw, 0, area, 0, 1);
    if (lk) {
        unsigned char *px = *(unsigned char **)(lk + 0);
        int pitchX = *(int *)(lk + 8);
        int pitchY = *(int *)(lk + 12);
        if (px && pitchX > 0 && pitchY > 0) {
            for (int y = 0; y < H; y++) {
                unsigned char *row = px + (long)y * pitchY;
                const unsigned char *s = E420Z_ICON + (long)y * W * 4;
                for (int x = 0; x < W; x++) {
                    unsigned char *p = row + (long)x * pitchX;
                    unsigned short v =
                        (unsigned short)(((s[0] >> 4) << 12) |
                                         ((s[1] >> 4) << 8) |
                                         ((s[2] >> 4) << 4) |
                                         (s[3] >> 4));
                    p[0] = (unsigned char)(v & 0xFF);
                    p[1] = (unsigned char)(v >> 8);
                }
            }
        }
        g_unlock_bmp(lk);
    }

    if (!stock) return raw;
    /* Clone the stock icon object (vtable + fields) and repoint its raw
     * bitmap at ours.  This keeps the exact wrapper class the stock menu
     * expects. */
    natartos_memcpy(g_icon_obj, stock, 80);
    *(void **)(g_icon_obj + 40) = raw;
    *(int *)(g_icon_obj + 56) = W;
    *(int *)(g_icon_obj + 60) = H;
    g_icon_obj[65] = 1;
    NTLOG("icon clone ok");
    return g_icon_obj;
}

/* Paint the E420Z logo into an existing stock icon's raw pixel buffer.
 * Reusing the stock wrapper keeps the menu's exact bitmap class/format. */
static void *paint_e420z_icon(void *icon) {
    if (!icon || !g_lock_bmp || !g_unlock_bmp) return 0;
    void *raw = *(void **)((char *)icon + 40);
    if (!raw) return 0;
    const int W = E420Z_ICON_W, H = E420Z_ICON_H;
    XRect area; area.x1 = 0; area.y1 = 0; area.x2 = W; area.y2 = H;
    unsigned char *lk = (unsigned char *)g_lock_bmp(raw, 0, area, 0, 1);
    if (!lk) return 0;
    unsigned char *px = *(unsigned char **)(lk + 0);
    int pitchX = *(int *)(lk + 8);
    int pitchY = *(int *)(lk + 12);
    if (px && pitchX > 0 && pitchY > 0) {
        for (int y = 0; y < H; y++) {
            unsigned char *row = px + (long)y * pitchY;
            const unsigned char *s = E420Z_ICON + (long)y * W * 4;
            for (int x = 0; x < W; x++) {
                unsigned char *p = row + (long)x * pitchX;
                unsigned short v =
                    (unsigned short)(((s[0] >> 4) << 12) |
                                     ((s[1] >> 4) << 8) |
                                     ((s[2] >> 4) << 4) |
                                     (s[3] >> 4));
                p[0] = (unsigned char)(v & 0xFF);
                p[1] = (unsigned char)(v >> 8);
            }
        }
    }
    g_unlock_bmp(lk);
    NTLOG("painted E420Z icon");
    return icon;
}

/* ── actions ────────────────────────────────────────────────────────────── */

static void defer_reload(int mode);

static int prepare_item(void *ds);
static int ds_is_wrapped(void *ds);

static void menu_action(void *obj, void *arg1, void *arg2, void *arg3) {
    (void)obj;
    NTLOG("action: E420Z -> stock settings panel");
    g_e420z_page = 1;
    if (g_settings_method) {
        NTLOG_HEX("settings method=", (unsigned long)g_settings_method);
        ((void (*)(void *, void *, void *, void *))g_settings_method)(
            g_settings_obj, arg1, arg2, arg3);
    } else if (g_open_settings) {
        g_open_settings();
    }
}

static void n3_action(void *obj) {
    sub_slot *s = (sub_slot *)obj;
    int idx = s ? s->idx : -1;
    NTLOG_INT("sub action=", idx);
    if (idx == SUB_COUNT - 1) {            /* BACK */
        defer_reload(0);
        return;
    }
    /* Placeholder: each row is a real stock row; wire its page/action later. */
}

static void defer_reload(int mode) {
    if (mode == 1 && !g_sub_ready) {
        NTLOG("submenu not ready");
        return;
    }
    g_mode = mode;
    /* Recreate the EW strings in the current frame; the ones from the last
     * menu Reload may already have been garbage-collected. */
    if (g_ds && ds_is_wrapped(g_ds)) prepare_item(g_ds);
    if (g_menu_self && g_reload_impl) {
        NTLOG_INT("reload mode=", mode);
        ((reload_fn)g_reload_impl)(g_menu_self);
    }
}

/* ── data source wrappers ───────────────────────────────────────────────── */

static int wrap_size(void *ds) {
    if (!g_orig_size) return 0;
    if (ds == g_ds) {
        if (g_mode == 1) return SUB_COUNT;
        return g_orig_size(ds) + 1;      /* stock rows + new N3 row */
    }
    return g_orig_size(ds);
}

static void *wrap_at(void *ds, int index) {
    if (!g_orig_at) return 0;
    if (ds == g_ds) {
        if (g_mode == 1) {
            if (index >= 0 && index < SUB_COUNT) return g_sub_item[index];
            return 0;
        }
        /* N3 first, then every original stock row unchanged. */
        if (index == 0 && g_item_ready) return g_item;
        return g_orig_at(ds, index - 1);
    }
    return g_orig_at(ds, index);
}

static int patch_ds(void *ds) {
    if (!ds) return 0;
    void **v = *(void ***)ds;
    if (!v) return 0;

    if (v[DS_SIZE_SLOT] == (void *)wrap_size) {
        g_ds = ds;
        g_ds_patched = 1;
        return 1;
    }

    g_orig_size = (count_fn)v[DS_SIZE_SLOT];
    g_orig_at = (get_item_fn)v[DS_AT_SLOT];
    if (!g_orig_size || !g_orig_at) return 0;

    for (int i = 0; i < 32; i++) g_ds_vmt[i] = v[i];
    g_ds_vmt[DS_SIZE_SLOT] = (void *)wrap_size;
    g_ds_vmt[DS_AT_SLOT] = (void *)wrap_at;
    *(void ***)ds = g_ds_vmt;

    g_ds = ds;
    g_ds_patched = 1;
    NTLOG("ds vtable copied");
    return 1;
}

static int ds_is_wrapped(void *ds) {
    void **v = ds ? *(void ***)ds : 0;
    return v && v[DS_SIZE_SLOT] == (void *)wrap_size;
}

/* ── E420Z content page (the stock Settings-style panel) ────────────────── */

static int wrap_size_more(void *ds) {
    if (!g_orig_size_more) return 0;
    if (g_e420z_page) return PAGE_COUNT;
    return g_orig_size_more(ds);
}

static void *wrap_at_more(void *ds, int index) {
    if (!g_orig_at_more) return 0;
    if (g_e420z_page) {
        if (index >= 0 && index < PAGE_COUNT) return g_page_item[index];
        return 0;
    }
    return g_orig_at_more(ds, index);
}

static int more_ds_wrapped(void *ds) {
    void **v = ds ? *(void ***)ds : 0;
    return v && v[DS_SIZE_SLOT] == (void *)wrap_size_more;
}

static int patch_more_ds(void *ds) {
    if (!ds) return 0;
    void **v = *(void ***)ds;
    if (!v) return 0;
    if (v[DS_SIZE_SLOT] == (void *)wrap_size_more) {
        g_ds_more = ds;
        return 1;
    }
    g_orig_size_more = (count_fn)v[DS_SIZE_SLOT];
    g_orig_at_more = (get_item_fn)v[DS_AT_SLOT];
    if (!g_orig_size_more || !g_orig_at_more) return 0;

    /* Capture the stock panel actions (Display, About, ...) before wrapping. */
    int n = g_orig_size_more(ds);
    for (int i = 0; i < 8 && i < n; i++) {
        void *it = g_orig_at_more(ds, i);
        if (!it) continue;
        unsigned long *ip = (unsigned long *)it;
        if (!ip[4]) continue;
        unsigned long *a = (unsigned long *)ip[4];
        g_more_act_obj[i] = (void *)a[4];
        g_more_act_fn[i] = (void *)a[5];
    }

    for (int i = 0; i < 32; i++) g_ds_more_vmt[i] = v[i];
    g_ds_more_vmt[DS_SIZE_SLOT] = (void *)wrap_size_more;
    g_ds_more_vmt[DS_AT_SLOT] = (void *)wrap_at_more;
    *(void ***)ds = g_ds_more_vmt;
    g_ds_more = ds;
    NTLOG("more ds copied");
    return 1;
}

static void call_stock_action(void *fn, void *obj,
                              void *a1, void *a2, void *a3) {
    if (fn) ((void (*)(void *, void *, void *, void *))fn)(obj, a1, a2, a3);
}

static void n3_page_action(void *obj, void *a1, void *a2, void *a3) {
    sub_slot *s = (sub_slot *)obj;
    int idx = s ? s->idx : -1;
    NTLOG_INT("page action=", idx);
    switch (idx) {
    case 0:  /* STATUS -> stock Status page */
        call_stock_action(g_main_act_fn[0], g_main_act_obj[0], a1, a2, a3);
        break;
    case 1:  /* BAND SCAN -> stock Transmission panel */
        call_stock_action(g_main_act_fn[2], g_main_act_obj[2], a1, a2, a3);
        break;
    case 2:  /* DISPLAY TEST -> stock Display panel */
        call_stock_action(g_more_act_fn[3], g_more_act_obj[3], a1, a2, a3);
        break;
    case 3:  /* ABOUT -> stock About page */
        call_stock_action(g_more_act_fn[4], g_more_act_obj[4], a1, a2, a3);
        break;
    case 4:  /* BACK -> close the panel */
        if (g_menu_self) {
            void **v = *(void ***)g_menu_self;
            if (v && v[DISMISS_SLOT])
                ((void (*)(void *))v[DISMISS_SLOT])(g_menu_self);
        }
        g_e420z_page = 0;
        break;
    }
}

static int prepare_page(void *ds) {
    if (!g_new_str || !g_orig_size_more || !g_orig_at_more) return 0;
    g_page_ready = 0;
    int n = g_orig_size_more(ds);
    if (n < 1) return 0;
    void *tmpl = g_orig_at_more(ds, 0);
    if (!tmpl) return 0;
    unsigned long *tp = (unsigned long *)tmpl;

    int ok = 1;
    for (int i = 0; i < PAGE_COUNT; i++) {
        g_page_slot[i].idx = i;
        if (tp[4])
            natartos_memcpy(g_page_act[i], (void *)tp[4], sizeof(g_page_act[i]));
        else
            natartos_memset(g_page_act[i], 0, sizeof(g_page_act[i]));
        ((unsigned long *)g_page_act[i])[4] = (unsigned long)&g_page_slot[i];
        ((unsigned long *)g_page_act[i])[5] = (unsigned long)n3_page_action;

        g_page_title[i] = g_new_str(PAGE_TITLES[i]);
        if (!g_page_title[i]) ok = 0;

        natartos_memcpy(g_page_item[i], tmpl, sizeof(g_page_item[i]));
        unsigned long *d = (unsigned long *)g_page_item[i];
        d[4] = (unsigned long)g_page_act[i];
        if (tp[5]) d[5] = tp[5];
        if (g_page_title[i]) d[16] = (unsigned long)g_page_title[i];
        d[17] = 0;
    }
    g_page_ready = ok;
    NTLOG("page items ready");
    return 1;
}

/* ── build items from a stock template ──────────────────────────────────── */

static int prepare_item(void *ds) {
    if (!g_new_str || !g_orig_size || !g_orig_at) return 0;
    g_item_ready = 0;
    g_sub_ready = 0;

    int n = g_orig_size(ds);
    if (n < 1) {
        NTLOG_INT("prepare: bad count=", n);
        return 0;
    }
    int ti = TEMPLATE_INDEX;
    if (ti >= n) ti = n - 1;
    void *tmpl = g_orig_at(ds, ti);
    if (!tmpl) {
        NTLOG("prepare: no template");
        return 0;
    }
    unsigned long *tp = (unsigned long *)tmpl;

    /* Capture the stock Status (0) and Transmission (2) actions for the
     * E420Z page, before we replace their rows in the sidebar. */
    for (int i = 0; i < n && i < 4; i++) {
        if (i != 0 && i != 2) continue;
        void *it = g_orig_at(ds, i);
        if (!it) continue;
        unsigned long *ip = (unsigned long *)it;
        if (!ip[4]) continue;
        unsigned long *a = (unsigned long *)ip[4];
        g_main_act_obj[i] = (void *)a[4];
        g_main_act_fn[i] = (void *)a[5];
    }

    g_n3_icon = 0;
    g_settings_obj = 0;
    g_settings_method = 0;
    if (n > 3) {
        void *settings = g_orig_at(ds, 3);     /* hexagon glyph + real action */
        if (settings) {
            unsigned long *sp = (unsigned long *)settings;
            g_n3_icon = (void *)sp[5];
            if (sp[4]) {
                unsigned long *act = (unsigned long *)sp[4];
                g_settings_obj = (void *)act[4];
                g_settings_method = (void *)act[5];
            }
        }
    }
    if (!g_n3_icon) g_n3_icon = (void *)tp[5];

    /* The E420Z row. */
    if (tp[4])
        natartos_memcpy(g_act, (void *)tp[4], sizeof(g_act));
    else
        natartos_memset(g_act, 0, sizeof(g_act));
    ((unsigned long *)g_act)[4] = (unsigned long)ds;
    ((unsigned long *)g_act)[5] = (unsigned long)menu_action;

    void *title = g_new_str("E420Z");
    void *sub = g_new_str("Tools");
    if (!title) {
        NTLOG("prepare: no title");
        return 0;
    }

    natartos_memcpy(g_item, tmpl, sizeof(g_item));
    unsigned long *d = (unsigned long *)g_item;
    d[4] = (unsigned long)g_act;
    if (g_n3_icon) d[5] = (unsigned long)g_n3_icon;
    else if (tp[5]) d[5] = tp[5];
    d[16] = (unsigned long)title;
    d[17] = sub ? (unsigned long)sub : 0;
    g_item_ready = 1;

    /* The N3 submenu rows. */
    int ok = 1;
    for (int i = 0; i < SUB_COUNT; i++) {
        g_sub_slot[i].idx = i;
        if (tp[4])
            natartos_memcpy(g_sub_act[i], (void *)tp[4], sizeof(g_sub_act[i]));
        else
            natartos_memset(g_sub_act[i], 0, sizeof(g_sub_act[i]));
        ((unsigned long *)g_sub_act[i])[4] = (unsigned long)&g_sub_slot[i];
        ((unsigned long *)g_sub_act[i])[5] = (unsigned long)n3_action;

        g_sub_title[i] = g_new_str(SUB_TITLES[i]);
        if (!g_sub_title[i]) ok = 0;

        natartos_memcpy(g_sub_item[i], tmpl, sizeof(g_sub_item[i]));
        unsigned long *sd = (unsigned long *)g_sub_item[i];
        sd[4] = (unsigned long)g_sub_act[i];
        if (tp[5]) sd[5] = tp[5];
        if (g_sub_title[i]) sd[16] = (unsigned long)g_sub_title[i];
        if (sub) sd[17] = (unsigned long)sub;
    }
    g_sub_ready = ok;

    NTLOG("prepare: items ready");
    return 1;
}

/* ── Reload / Dismiss hooks ─────────────────────────────────────────────── */

static void hook_reload(void *self) {
    reload_fn orig = (reload_fn)g_reload_impl;
    g_menu_self = self;

    void **vmt = *(void ***)self;
    const char *cls = "?";
    if ((void *)vmt == g_vmt_main) cls = "MAIN";
    else if ((void *)vmt == g_vmt_more) cls = "MORE";

    unsigned long *p = (unsigned long *)self;
    void *ds = (void *)p[73];

    int count = -1;
    if (ds) {
        void **dv = *(void ***)ds;
        if (dv && dv[DS_SIZE_SLOT]) count = ((count_fn)dv[DS_SIZE_SLOT])(ds);
    }
    NTLOG("reload"); NTLOG(cls); NTLOG_INT("items=", count);

    int inject = sys_faccessat(AT_FDCWD, FLAG_INJECT, F_OK) == 0;
    if (cls[1] == 'O') {
        if (g_e420z_page && ds) {
            if (!more_ds_wrapped(ds)) patch_more_ds(ds);
            if (more_ds_wrapped(ds)) prepare_page(ds);
        }
    } else if (inject && ds) {
        if (!ds_is_wrapped(ds)) patch_ds(ds);
        if (ds_is_wrapped(ds)) prepare_item(ds);
    }

    if (orig) orig(self);

    if (ds) {
        if (g_e420z_page && more_ds_wrapped(ds)) {
            if (g_set_noi) g_set_noi(self, 0);
            void **v = *(void ***)self;
            if (v && v[POSTRELOAD_SLOT])
                ((void (*)(void *))v[POSTRELOAD_SLOT])(self);
        } else if (inject && ds_is_wrapped(ds)) {
            if (g_set_noi) g_set_noi(self, 0);
            void **v = *(void ***)self;
            if (v && v[POSTRELOAD_SLOT])
                ((void (*)(void *))v[POSTRELOAD_SLOT])(self);
        }
    }
}

static void hook_dismiss(void *self) {
    g_mode = 0;
    g_e420z_page = 0;                 /* reopen the stock rows next time */
    if (g_dismiss_impl)
        ((void (*)(void *))g_dismiss_impl)(self);
}

static void hook_dismiss_more(void *self) {
    g_e420z_page = 0;
    if (g_dismiss_more_impl)
        ((void (*)(void *))g_dismiss_more_impl)(self);
}

/* ── vtable patching (loader late thread) ───────────────────────────────── */

static int patch_slot(void **v, int slot, void *new_fn, void **out_orig) {
    void *cur = v[slot];
    if (!cur || cur == new_fn) return cur == new_fn;
    *out_orig = cur;
    unsigned long page = (unsigned long)&v[slot] & ~(unsigned long)4095;
    long mr = sys_mprotect((void *)page, 8192, PROT_READ | PROT_WRITE);
    if (mr < 0) return 0;
    v[slot] = new_fn;
    sys_mprotect((void *)page, 8192, PROT_READ);
    return 1;
}

static int patch_menu(void *vmt, const char *name, int *patched) {
    if (!vmt || *patched) return 0;
    void **v = (void **)vmt;
    NTLOG(name); NTLOG_HEX("vmt=", (unsigned long)vmt);

    int r = patch_slot(v, RELOAD_SLOT, (void *)hook_reload, &g_reload_impl);
    int d = 1;
    if (vmt == g_vmt_main)
        d = patch_slot(v, DISMISS_SLOT, (void *)hook_dismiss, &g_dismiss_impl);
    else
        d = patch_slot(v, DISMISS_SLOT, (void *)hook_dismiss_more,
                       &g_dismiss_more_impl);
    NTLOG_INT("reload patch=", r);
    NTLOG_INT("dismiss patch=", d);
    if (r && d) {
        *patched = 1;
        return 1;
    }
    return 0;
}

int n3_menu_late_init(void) {
    if (!g_loader_dlsym) return 0;
    if (!g_vmt_main)
        g_vmt_main = g_loader_dlsym(RTLD_DEFAULT, "__n3_main_menu_vmt");
    if (!g_vmt_more)
        g_vmt_more = g_loader_dlsym(RTLD_DEFAULT, "__n3_more_menu_vmt");

    patch_menu(g_vmt_main, "MAIN", &g_patched_main);
    patch_menu(g_vmt_more, "MORE", &g_patched_more);
    return g_patched_main && g_patched_more;
}

/* ── mod entry ──────────────────────────────────────────────────────────── */

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_loader_dlsym = loader_dlsym;
    NTLOG("=== init ===");
    g_new_str = (new_str_fn)loader_dlsym(RTLD_DEFAULT, "EwNewStringAnsi");
    g_set_noi = (set_noi_fn)loader_dlsym(
        RTLD_DEFAULT, "CoreVerticalList_OnSetNoOfItems");
    g_set_h = (set_h_fn)loader_dlsym(
        RTLD_DEFAULT, "CoreVerticalList_OnSetItemHeight");
    g_create_bmp = (create_bmp_fn)loader_dlsym(
        RTLD_DEFAULT, "EwCreateBitmap");
    g_lock_bmp = (lock_bmp_fn)loader_dlsym(RTLD_DEFAULT, "EwLockBitmap");
    g_unlock_bmp = (unlock_bmp_fn)loader_dlsym(
        RTLD_DEFAULT, "EwUnlockBitmap");
    g_new_obj = (new_obj_fn)loader_dlsym(
        RTLD_DEFAULT, "EwNewObjectIndirect");
    g_vmt_res_bmp = loader_dlsym(RTLD_DEFAULT, "__vmt_ResourcesBitmap");
    g_res_bmp_init = (res_init_fn)loader_dlsym(
        RTLD_DEFAULT, "ResourcesBitmap_Init");
    g_load_bmp = (load_bmp_fn)loader_dlsym(RTLD_DEFAULT, "EwLoadBitmap");
    g_open_settings = (void_fn)loader_dlsym(
        RTLD_DEFAULT, "DuMenuItemsEntryActions_AppSettingsEntryAction");
    NTLOG_HEX("new_str=", (unsigned long)g_new_str);
    NTLOG_HEX("set_noi=", (unsigned long)g_set_noi);
    NTLOG_HEX("set_h=", (unsigned long)g_set_h);
    NTLOG_HEX("create_bmp=", (unsigned long)g_create_bmp);
    NTLOG_HEX("vmt_bmp=", (unsigned long)g_vmt_res_bmp);
    NTLOG_HEX("res_init=", (unsigned long)g_res_bmp_init);
    NTLOG_HEX("load_bmp=", (unsigned long)g_load_bmp);
    return 1;
}

int natartos_mod_register(void *(*loader_dlsym)(void *, const char *)) {
    (void)loader_dlsym;
    return 1;
}
