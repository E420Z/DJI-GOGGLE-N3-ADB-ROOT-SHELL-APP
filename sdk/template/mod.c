/* Template N3 app. Copy this folder, rename, and edit on_tick/on_key. */
#define NTLOG_PREFIX "hello"
#include "natartos_common.h"
#include "n3app.h"

static void u2s(unsigned int v, char *out) {
    char rev[12];
    int r = 0, d = 0;
    if (v == 0) rev[r++] = '0';
    while (v > 0) { rev[r++] = (char)('0' + v % 10); v /= 10; }
    while (r > 0) out[d++] = rev[--r];
    out[d] = 0;
}

static void on_tick(n3_surface *s, unsigned int frame) {
    n3_text(s, 10, 6, "HELLO N3", 4, 0xFFFFFFFF);
    n3_text(s, 10, 46, "SDK TEMPLATE - LIVE", 2, 0xFFB9A6E8);

    int bw = s->w - 20;
    n3_fill(s, 10, 86, bw, 14, 0xFF2A2440);
    n3_fill(s, 10, 86, (int)((frame % 100) * (unsigned)bw / 100), 14, 0xFF7A2BE0);

    char buf[16];
    u2s(frame, buf);
    n3_text(s, 10, 116, "FRAME", 3, 0xFFB9A6E8);
    n3_text(s, 10 + n3_text_width("FRAME ", 3), 116, buf, 3, 0xFFFFFFFF);

    n3_text(s, 10, 156, "ENTER LOGS ITS CODE", 2, 0xFFB9A6E8);
    n3_text(s, 10, 178, "BACK CLOSES THIS WINDOW", 2, 0xFFB9A6E8);
}

static void on_key(int key) {
    if (key == N3_KEY_ENTER) NTLOG("key ENTER");
    else if (key == N3_KEY_BACK) NTLOG("key BACK");
    else NTLOG_INT("key code=", key);
}

static const n3_app g_app = {
    .name = "HELLO",
    .w = 0, .h = 0,          /* 0 => default centred window */
    .on_tick = on_tick,
    .on_key = on_key,
};

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    return n3_start(&g_app, loader_dlsym);
}
