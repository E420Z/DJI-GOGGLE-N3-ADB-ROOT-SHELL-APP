/* N3 menu demo — swipe to move, tap/ENTER to select, BACK to go back/exit. */
#define NTLOG_PREFIX "n3menu"
#include "natartos_common.h"
#include "n3app.h"

#define COUNT 5

static const char *ITEMS[COUNT] = {
    "STATUS", "SDR SCAN", "DISPLAY TEST", "ABOUT", "EXIT"
};

static int g_sel;
static int g_detail = -1;
static unsigned int g_frame;

static const n3_color C_WHITE = 0xFFFFFFFF;
static const n3_color C_DIM   = 0xFFB9A6E8;
static const n3_color C_SEL   = 0xFF3A1E66;
static const n3_color C_ACC   = 0xFFB44BFF;

static void u2s(unsigned int v, char *out) {
    char rev[12]; int r = 0, d = 0;
    if (v == 0) rev[r++] = '0';
    while (v > 0) { rev[r++] = (char)('0' + v % 10); v /= 10; }
    while (r > 0) out[d++] = rev[--r];
    out[d] = 0;
}

static void draw_list(n3_surface *s) {
    int y = 10;
    for (int i = 0; i < COUNT; i++) {
        if (i == g_sel) {
            n3_fill(s, 8, y - 6, s->w - 16, 34, C_SEL);
            n3_text(s, 16, y, ">", 2, C_ACC);
            n3_text(s, 40, y, ITEMS[i], 2, C_WHITE);
        } else {
            n3_text(s, 40, y, ITEMS[i], 2, C_DIM);
        }
        y += 42;
    }
}

static void draw_status(n3_surface *s) {
    n3_text(s, 10, 4, "STATUS", 3, C_WHITE);
    n3_fill(s, 10, 34, s->w - 20, 2, C_ACC);
    n3_text(s, 10, 48, "THEME      PURPLE", 2, C_DIM);
    n3_text(s, 10, 72, "DISPLAY    1920X1080", 2, C_DIM);
    n3_text(s, 10, 96, "SDK        N3APP V0.1", 2, C_DIM);
    n3_text(s, 10, 120, "LINK       GFSK MONITOR", 2, C_DIM);
    n3_text(s, 10, 150, "READ-ONLY / BENCH ONLY", 2, C_ACC);
}

static void draw_scan(n3_surface *s) {
    n3_text(s, 10, 4, "SDR SCAN", 3, C_WHITE);
    n3_fill(s, 10, 34, s->w - 20, 2, C_ACC);
    n3_text(s, 10, 50, "SIMULATED - NO RADIO I/O", 2, C_DIM);

    for (int i = 0; i < 16; i++) {
        int h = 10 + (int)((g_frame * 7 + i * 37) % 70);
        n3_fill(s, 12 + i * 18, 150 - h, 12, h, C_ACC);
    }
    n3_text(s, 10, 166, "LOGGED METRICS ONLY", 2, C_DIM);
}

static void draw_display(n3_surface *s) {
    n3_text(s, 10, 4, "DISPLAY TEST", 3, C_WHITE);
    n3_fill(s, 10, 34, s->w - 20, 2, C_ACC);
    n3_color bars[6] = {0xFFFFFFFF, 0xFFFF4040, 0xFF40FF40,
                        0xFF4080FF, 0xFFFFE040, 0xFFB44BFF};
    for (int i = 0; i < 6; i++)
        n3_fill(s, 12 + i * 60, 50, 56, 90, bars[i]);
    n3_text(s, 10, 150, "COLOR BARS + TEXT", 2, C_DIM);
}

static void draw_about(n3_surface *s) {
    n3_text(s, 10, 4, "ABOUT", 3, C_WHITE);
    n3_fill(s, 10, 34, s->w - 20, 2, C_ACC);
    n3_text(s, 10, 50, "N3 APP SDK V0.1", 2, C_WHITE);
    n3_text(s, 10, 74, "SAFE OVERLAY WINDOW", 2, C_DIM);
    n3_text(s, 10, 98, "NO FRAME SUPPRESSION", 2, C_DIM);
    n3_text(s, 10, 122, "BACK RESTORES THE UI", 2, C_DIM);
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
    n3_text(s, 10, s->h - 18, "BACK = LIST", 1, C_DIM);
}

static void activate(int i) {
    if (i == 4) { n3_hide(); return; }
    g_detail = i;
}

static void on_key(int key) {
    if (key == N3_KEY_ENTER) {
        if (g_detail < 0) activate(g_sel);
        else activate(g_detail);          /* re-open / refresh */
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
    .name = "N3 MENU",
    .w = 760, .h = 420,
    .manual_back = 1,
    .on_tick = on_tick,
    .on_key = on_key,
    .on_swipe = on_swipe,
    .on_tap = on_tap,
};

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    return n3_start(&g_app, loader_dlsym);
}
