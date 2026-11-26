/* E420Z panel — stock-styled content panel beside the left sidebar.
 * Opened from the native E420Z row.  Up/down moves, center selects,
 * Back returns to the list / closes the panel. */
#define NTLOG_PREFIX "e420z"
#include "natartos_common.h"
#include "n3app.h"

#define COUNT 5

static const char *ITEMS[COUNT] = {
    "STATUS", "BAND SCAN", "DISPLAY TEST", "ABOUT", "EXIT"
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
    n3_text(s, 12, 58, "THEME       PURPLE", 2, C_DIM);
    n3_text(s, 12, 88, "DISPLAY     1920 X 1080", 2, C_DIM);
    n3_text(s, 12, 118, "UI          EW / NATIVE MENU", 2, C_DIM);
    n3_text(s, 12, 148, "LINK        GFSK MONITOR", 2, C_DIM);
    n3_text(s, 12, 190, "READ-ONLY / BENCH ONLY", 2, C_ACC);
}

static void draw_scan(n3_surface *s) {
    n3_text(s, 8, 4, "BAND SCAN", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    n3_text(s, 12, 58, "SIMULATED - NO RADIO I/O", 2, C_DIM);
    for (int i = 0; i < 16; i++) {
        int h = 18 + (int)((g_frame * 7 + i * 37) % 90);
        n3_fill(s, 14 + i * 20, 250 - h, 14, h, C_ACC);
    }
    n3_text(s, 12, 270, "LOGGED METRICS ONLY", 2, C_DIM);
}

static void draw_display(n3_surface *s) {
    n3_text(s, 8, 4, "DISPLAY TEST", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    n3_color bars[6] = {0xFFFFFFFF, 0xFFFF4040, 0xFF40FF40,
                        0xFF4080FF, 0xFFFFE040, 0xFFB44BFF};
    for (int i = 0; i < 6; i++)
        n3_fill(s, 14 + i * 62, 60, 58, 100, bars[i]);
    n3_text(s, 12, 180, "COLOR BARS + TEXT", 2, C_DIM);
}

static void draw_about(n3_surface *s) {
    n3_text(s, 8, 4, "ABOUT", 3, C_WHITE);
    n3_fill(s, 8, 40, s->w - 16, 1, C_LINE);
    n3_text(s, 12, 58, "E420Z / N3 APP SDK", 2, C_WHITE);
    n3_text(s, 12, 88, "STOCK-UI MENU INJECTION", 2, C_DIM);
    n3_text(s, 12, 118, "NO FRAME SUPPRESSION", 2, C_DIM);
    n3_text(s, 12, 148, "BACK RESTORES THE UI", 2, C_DIM);
    n3_text(s, 12, 190, "BENCH / READ-ONLY", 2, C_ACC);
}

static void on_tick(n3_surface *s, unsigned int frame) {
    g_frame = frame;
    if (g_detail < 0) { draw_list(s); return; }
    switch (g_detail) {
    case 0: draw_status(s); break;
    case 1: draw_scan(s); break;
    case 2: draw_display(s); break;
    case 3: draw_about(s); break;
    default: draw_list(s); break;
    }
    n3_text(s, 12, s->h - 26, "BACK = LIST", 2, C_DIM);
}

static void activate(int i) {
    if (i == 4) { n3_hide(); return; }
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
    if (g_detail >= 0) {
        if (dy > 0 || dx > 0) g_detail = -1;
        return;
    }
    if (dx > 0) { activate(g_sel); return; }   /* right/center = select */
    if (dy < 0) g_sel = (g_sel + COUNT - 1) % COUNT;
    else if (dy > 0) g_sel = (g_sel + 1) % COUNT;
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
