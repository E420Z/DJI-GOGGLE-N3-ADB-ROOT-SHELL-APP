/* UI template — a stock-styled content panel beside the left sidebar.
 *
 * Build:
 *   powershell -ExecutionPolicy Bypass -File sdk\build.ps1 `
 *       -Src ..\mods\yourpanel\mod.c -Out ..\app\plugins\yourpanel\files\yourpanel.so
 *
 * Open it from a native row by touching /data/local/tmp/n3_app_on
 * (or set a different FLAG_ON in n3app.h).
 *
 * Geometry matches the stock Settings panel: x=360, y=85, w=670, h=910.
 * The n3app window chrome is stock-styled (dark neutral, subtle border,
 * centered title, centered footer).
 */
#define NTLOG_PREFIX "uitpl"
#include "natartos_common.h"
#include "n3app.h"

#define COUNT 4

static const char *ITEMS[COUNT] = {
    "STATUS", "TOOLS", "ABOUT", "EXIT"
};

static int g_sel;
static int g_detail = -1;
static unsigned int g_frame;

static const n3_color C_WHITE = 0xFFFFFFFF;
static const n3_color C_DIM   = 0xFFB0B0B0;
static const n3_color C_SEL   = 0xFF3A2350;
static const n3_color C_ACC   = 0xFFB44BFF;
static const n3_color C_LINE  = 0xFF3A3A3A;

static void draw_list(n3_surface *s) {
    int y = 12;
    for (int i = 0; i < COUNT; i++) {
        if (i == g_sel) {
            n3_fill(s, 8, y - 4, s->w - 16, 112, C_SEL);
            n3_fill(s, 8, y - 4, 4, 112, C_ACC);
        }
        n3_text(s, 32, y + 28, ITEMS[i], 3,
                i == g_sel ? C_WHITE : C_DIM);
        n3_text(s, s->w - 34, y + 28, ">", 3, C_DIM);
        y += 140;
    }
    n3_fill(s, 0, 0, s->w, 1, C_LINE);
}

static void draw_status(n3_surface *s) {
    n3_text(s, 8, 4, "STATUS", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    n3_text(s, 12, 58, "YOUR STATUS LINES HERE", 2, C_DIM);
}

static void draw_tools(n3_surface *s) {
    n3_text(s, 8, 4, "TOOLS", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    for (int i = 0; i < 12; i++) {
        int h = 18 + (int)((g_frame * 7 + i * 37) % 90);
        n3_fill(s, 14 + i * 26, 240 - h, 18, h, C_ACC);
    }
    n3_text(s, 12, 260, "YOUR TOOL OUTPUT HERE", 2, C_DIM);
}

static void draw_about(n3_surface *s) {
    n3_text(s, 8, 4, "ABOUT", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    n3_text(s, 12, 58, "YOUR PANEL NAME", 2, C_WHITE);
    n3_text(s, 12, 88, "BACK = LIST / CLOSE", 2, C_DIM);
}

static void on_tick(n3_surface *s, unsigned int frame) {
    g_frame = frame;
    if (g_detail < 0) { draw_list(s); return; }
    switch (g_detail) {
    case 0: draw_status(s); break;
    case 1: draw_tools(s); break;
    case 2: draw_about(s); break;
    default: draw_list(s); break;
    }
    n3_text(s, 12, s->h - 26, "BACK = LIST", 2, C_DIM);
}

static void activate(int i) {
    if (i == COUNT - 1) { n3_hide(); return; }
    g_detail = i;
}

static void on_key(int key) {
    if (key == N3_KEY_ENTER) {
        if (g_detail < 0) activate(g_sel);
    } else if (key == N3_KEY_BACK) {
        if (g_detail >= 0) { g_detail = -1; return; }
        n3_hide();
    }
}

static void on_swipe(int dx, int dy) {
    (void)dx;
    if (g_detail >= 0) { if (dy > 0) g_detail = -1; return; }
    if (dy < 0) g_sel = (g_sel + 1) % COUNT;
    else if (dy > 0) g_sel = (g_sel + COUNT - 1) % COUNT;
}

static void on_tap(int x, int y) {
    (void)x; (void)y;
    if (g_detail < 0) activate(g_sel);
}

static const n3_app g_app = {
    .name = "E420Z",
    .x = 360, .y = 85, .w = 670, .h = 910,
    .manual_back = 1,
    .on_tick = on_tick,
    .on_key = on_key,
    .on_swipe = on_swipe,
    .on_tap = on_tap,
};

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    return n3_start(&g_app, loader_dlsym);
}
