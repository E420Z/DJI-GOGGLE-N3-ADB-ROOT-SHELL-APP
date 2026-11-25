/*
 * n3paint — safe on-screen panel for the N3 UI.
 *
 * This mod does NOT hook duss_hal_display_push_frame and never suppresses a
 * frame. While /data/local/tmp/n3_app_on exists, a helper thread composites a
 * small panel into the live 1920x1080 dmabuf surfaces. The panel area is
 * backed up before the first paint and restored when the flag is removed.
 *
 * BACK (gpio_keys event0, KEY_BACK=158) removes the flag, so the panel exits.
 *
 * Build: zig cc -target aarch64-linux-gnu -shared -fPIC -nostdlib ...
 */
#define NTLOG_PREFIX "paint"
#include "natartos_common.h"

#define __NR_unlinkat 35

#define O_NONBLOCK 0x800

#define EV_KEY 1
#define KEY_BACK 158

struct input_event_t { long sec, usec; unsigned short type, code; int value; };

static inline long sys_unlinkat(int dirfd, const char *path, int flags) {
    register long x0 __asm__("x0") = dirfd;
    register long x1 __asm__("x1") = (long)path;
    register long x2 __asm__("x2") = flags;
    register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);
typedef void *(*dlsym_fn)(void *, const char *);
static dlsym_fn g_dlsym;

#define FRAME_SIZE (1920 * 1080 * 4)
#define FRAME_W 1920
#define FRAME_H 1080

#define FLAG_ON   "/data/local/tmp/n3_app_on"
#define FLAG_EXIT "/data/local/tmp/n3_app_exit"
#define MAPS_PATH "/proc/self/maps"

/* Panel geometry (centred). */
#define PX 560
#define PY 360
#define PW 800
#define PH 340

/* Backup of the panel region, one per dmabuf slot. BSS, not file data. */
static unsigned int g_backup[2][PW * PH];
static int g_have_backup[2];

static unsigned long g_fbs[4];
static int g_fb_count;
static long g_last_scan_ms;

/* ------------------------------------------------------------------ utils */

static long now_ms(void) {
    struct timespec_t t;
    register long x0 __asm__("x0") = 1; /* CLOCK_MONOTONIC */
    register long x1 __asm__("x1") = (long)&t;
    register long x8 __asm__("x8") = 113; /* clock_gettime */
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return (long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int line_has(const char *s, int n, const char *needle) {
    int m = 0;
    while (needle[m]) m++;
    for (int i = 0; i + m <= n; i++) {
        int j = 0;
        while (j < m && s[i + j] == needle[j]) j++;
        if (j == m) return 1;
    }
    return 0;
}

static unsigned long parse_hex(const char **p) {
    unsigned long v = 0;
    const char *s = *p;
    while (1) {
        char c = *s;
        int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else break;
        v = (v << 4) | (unsigned)d;
        s++;
    }
    *p = s;
    return v;
}

static int find_dmabufs(void) {
    int fd = (int)sys_openat(AT_FDCWD, MAPS_PATH, O_RDONLY, 0);
    if (fd < 0) return 0;
    char buf[1024];
    int len = 0, count = 0;
    while (1) {
        if (len < (int)sizeof(buf) - 1) {
            long got = sys_read(fd, buf + len, sizeof(buf) - 1 - len);
            if (got <= 0 && len == 0) break;
            if (got > 0) len += got;
        }
        buf[len] = 0;
        int nl = -1;
        for (int i = 0; i < len; i++) if (buf[i] == '\n') { nl = i; break; }
        if (nl < 0) { if (len >= (int)sizeof(buf) - 1) { len = 0; continue; } break; }
        const char *p = buf;
        unsigned long start = parse_hex(&p);
        if (*p == '-') p++;
        unsigned long end = parse_hex(&p);
        if ((long)(end - start) == FRAME_SIZE &&
            line_has(buf, nl, "dmabuf") && count < 4)
            g_fbs[count++] = start;
        int rem = len - nl - 1;
        for (int i = 0; i < rem; i++) buf[i] = buf[nl + 1 + i];
        len = rem;
    }
    sys_close(fd);
    return count;
}

/* ------------------------------------------------------------------- draw */

static inline void px(unsigned int *fb, int x, int y, unsigned int c) {
    if (x < 0 || x >= FRAME_W || y < 0 || y >= FRAME_H) return;
    fb[(long)y * FRAME_W + x] = c;
}

static void rect(unsigned int *fb, int x, int y, int w, int h, unsigned int c) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            px(fb, x + i, y + j, c);
}

static void frame_rect(unsigned int *fb, int x, int y, int w, int h,
                       int t, unsigned int c) {
    rect(fb, x, y, w, t, c);
    rect(fb, x, y + h - t, w, t, c);
    rect(fb, x, y, t, h, c);
    rect(fb, x + w - t, y, t, h, c);
}

/* 5x7 font, row-major, low 5 bits per row. */
static const unsigned char *glyph(char ch) {
    static const unsigned char sp[7] = {0,0,0,0,0,0,0};
    static const unsigned char g0[7] = {0x0E,0x11,0x13,0x15,0x19,0x11,0x0E};
    static const unsigned char g1[7] = {0x04,0x0C,0x04,0x04,0x04,0x04,0x0E};
    static const unsigned char g2[7] = {0x0E,0x11,0x01,0x02,0x04,0x08,0x1F};
    static const unsigned char g3[7] = {0x1F,0x02,0x04,0x02,0x01,0x11,0x0E};
    static const unsigned char g4[7] = {0x02,0x06,0x0A,0x12,0x1F,0x02,0x02};
    static const unsigned char g5[7] = {0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E};
    static const unsigned char g6[7] = {0x06,0x08,0x10,0x1E,0x11,0x11,0x0E};
    static const unsigned char g7[7] = {0x1F,0x01,0x02,0x04,0x08,0x08,0x08};
    static const unsigned char g8[7] = {0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E};
    static const unsigned char g9[7] = {0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C};
    static const unsigned char gA[7] = {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11};
    static const unsigned char gB[7] = {0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E};
    static const unsigned char gC[7] = {0x0E,0x11,0x10,0x10,0x10,0x11,0x0E};
    static const unsigned char gD[7] = {0x1C,0x12,0x11,0x11,0x11,0x12,0x1C};
    static const unsigned char gE[7] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F};
    static const unsigned char gF[7] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x10};
    static const unsigned char gG[7] = {0x0E,0x11,0x10,0x17,0x11,0x11,0x0F};
    static const unsigned char gH[7] = {0x11,0x11,0x11,0x1F,0x11,0x11,0x11};
    static const unsigned char gI[7] = {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E};
    static const unsigned char gJ[7] = {0x07,0x02,0x02,0x02,0x02,0x12,0x0C};
    static const unsigned char gK[7] = {0x11,0x12,0x14,0x18,0x14,0x12,0x11};
    static const unsigned char gL[7] = {0x10,0x10,0x10,0x10,0x10,0x10,0x1F};
    static const unsigned char gM[7] = {0x11,0x1B,0x15,0x15,0x11,0x11,0x11};
    static const unsigned char gN[7] = {0x11,0x19,0x19,0x15,0x13,0x13,0x11};
    static const unsigned char gO[7] = {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E};
    static const unsigned char gP[7] = {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10};
    static const unsigned char gQ[7] = {0x0E,0x11,0x11,0x11,0x15,0x12,0x0D};
    static const unsigned char gR[7] = {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11};
    static const unsigned char gS[7] = {0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E};
    static const unsigned char gT[7] = {0x1F,0x04,0x04,0x04,0x04,0x04,0x04};
    static const unsigned char gU[7] = {0x11,0x11,0x11,0x11,0x11,0x11,0x0E};
    static const unsigned char gV[7] = {0x11,0x11,0x11,0x11,0x11,0x0A,0x04};
    static const unsigned char gW[7] = {0x11,0x11,0x11,0x15,0x15,0x1B,0x11};
    static const unsigned char gX[7] = {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11};
    static const unsigned char gY[7] = {0x11,0x11,0x0A,0x04,0x04,0x04,0x04};
    static const unsigned char gZ[7] = {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F};
    static const unsigned char dash[7] = {0,0,0,0x0E,0,0,0};
    static const unsigned char dot[7]  = {0,0,0,0,0,0x0C,0x0C};
    static const unsigned char colon[7]= {0,0x0C,0x0C,0,0x0C,0x0C,0};
    static const unsigned char slash[7]= {0x01,0x02,0x02,0x04,0x08,0x08,0x10};
    switch (ch) {
    case '0': return g0; case '1': return g1; case '2': return g2;
    case '3': return g3; case '4': return g4; case '5': return g5;
    case '6': return g6; case '7': return g7; case '8': return g8;
    case '9': return g9;
    case 'A': return gA; case 'B': return gB; case 'C': return gC;
    case 'D': return gD; case 'E': return gE; case 'F': return gF;
    case 'G': return gG; case 'H': return gH; case 'I': return gI;
    case 'J': return gJ; case 'K': return gK; case 'L': return gL;
    case 'M': return gM; case 'N': return gN; case 'O': return gO;
    case 'P': return gP; case 'Q': return gQ; case 'R': return gR;
    case 'S': return gS; case 'T': return gT; case 'U': return gU;
    case 'V': return gV; case 'W': return gW; case 'X': return gX;
    case 'Y': return gY; case 'Z': return gZ;
    case '-': return dash; case '.': return dot;
    case ':': return colon; case '/': return slash;
    default:  return sp;
    }
}

static int text_width(const char *s, int scale) {
    int n = 0;
    while (s[n]) n++;
    return n * 6 * scale;
}

static void text(unsigned int *fb, int x, int y, const char *s,
                 int scale, unsigned int c) {
    for (int k = 0; s[k]; k++) {
        const unsigned char *g = glyph(s[k]);
        int ox = x + k * 6 * scale;
        for (int r = 0; r < 7; r++) {
            unsigned char row = g[r];
            for (int col = 0; col < 5; col++) {
                if (row & (1 << (4 - col)))
                    rect(fb, ox + col * scale, y + r * scale, scale, scale, c);
            }
        }
    }
}

/* --------------------------------------------------------------- painting */

static const unsigned int COL_BG     = 0xFF14121C;
static const unsigned int COL_BORDER = 0xFFB44BFF;
static const unsigned int COL_TEXT   = 0xFFFFFFFF;
static const unsigned int COL_DIM    = 0xFFB9A6E8;
static const unsigned int COL_BAR    = 0xFF7A2BE0;

static int g_anim;

static void save_region(unsigned int *fb, int slot) {
    if (g_have_backup[slot]) return;
    for (int j = 0; j < PH; j++)
        for (int i = 0; i < PW; i++)
            g_backup[slot][j * PW + i] = fb[(long)(PY + j) * FRAME_W + (PX + i)];
    g_have_backup[slot] = 1;
}

static void restore_region(unsigned int *fb, int slot) {
    if (!g_have_backup[slot]) return;
    for (int j = 0; j < PH; j++)
        for (int i = 0; i < PW; i++)
            fb[(long)(PY + j) * FRAME_W + (PX + i)] = g_backup[slot][j * PW + i];
    g_have_backup[slot] = 0;
}

static void draw_panel(unsigned int *fb) {
    rect(fb, PX, PY, PW, PH, COL_BG);
    frame_rect(fb, PX, PY, PW, PH, 4, COL_BORDER);

    text(fb, PX + 40, PY + 40, "N3 APP", 6, COL_TEXT);
    text(fb, PX + 40, PY + 100, "PAINT OVERLAY - NO FRAME SUPPRESSION", 2, COL_DIM);

    /* animated progress bar */
    int bx = PX + 40, by = PY + 160, bw = PW - 80, bh = 18;
    rect(fb, bx, by, bw, bh, 0xFF2A2440);
    int fill = (g_anim % 100) * bw / 100;
    rect(fb, bx, by, fill, bh, COL_BAR);

    /* counter */
    char buf[16];
    int v = g_anim % 1000, d = 0;
    if (v == 0) buf[d++] = '0';
    char rev[8]; int r = 0;
    while (v > 0) { rev[r++] = (char)('0' + v % 10); v /= 10; }
    while (r > 0) buf[d++] = rev[--r];
    buf[d] = 0;
    text(fb, PX + 40, PY + 210, "FRAME", 3, COL_DIM);
    text(fb, PX + 40 + text_width("FRAME ", 3), PY + 210, buf, 3, COL_TEXT);
    text(fb, PX + 40, PY + 270, "BACK = EXIT", 3, COL_DIM);

    g_anim++;
}

static int flag_on(void) {
    return sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) == 0;
}

/* ------------------------------------------------------- back watcher ---- */

static void *paint_thread_fn(void *arg) {
    (void)arg;
    NTLOG("paint thread: start");
    struct timespec_t ts = { 0, 60000000 }; /* 60 ms */
    int fd = -1;
    int was_on = 0;
    while (1) {
        long ms = now_ms();
        if (ms - g_last_scan_ms > 2000) {
            g_fb_count = find_dmabufs();
            g_last_scan_ms = ms;
        }

        int on = flag_on();
        if (on && g_fb_count > 0) {
            for (int i = 0; i < g_fb_count; i++) {
                unsigned int *fb = (unsigned int *)g_fbs[i];
                save_region(fb, i < 2 ? i : 0);
                draw_panel(fb);
            }
        } else if (!on && was_on) {
            for (int i = 0; i < g_fb_count; i++) {
                unsigned int *fb = (unsigned int *)g_fbs[i];
                restore_region(fb, i < 2 ? i : 0);
            }
            NTLOG("paint: restored panel area");
        }
        was_on = on;

        /* BACK exits the panel. */
        if (fd < 0)
            fd = (int)sys_openat(AT_FDCWD, "/dev/input/event0",
                                 O_RDONLY | O_NONBLOCK, 0);
        if (fd >= 0) {
            struct input_event_t ev;
            while (sys_read(fd, &ev, sizeof(ev)) == (long)sizeof(ev)) {
                if (ev.type == EV_KEY && ev.code == KEY_BACK && ev.value == 1) {
                    sys_unlinkat(AT_FDCWD, FLAG_ON, 0);
                    int x = (int)sys_openat(AT_FDCWD, FLAG_EXIT,
                                            O_WRONLY | O_CREAT | O_TRUNC, 0666);
                    if (x >= 0) sys_close(x);
                    NTLOG("paint: BACK -> exit");
                }
            }
        }
        sys_nanosleep(&ts, 0);
    }
    return 0;
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    NTLOG("paint: init");
    pthread_create_fn pcreate =
        g_dlsym ? (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create") : 0;
    if (!pcreate) { NTLOG("paint: no pthread_create"); return -1; }
    unsigned long tid;
    int ret = pcreate(&tid, 0, paint_thread_fn, 0);
    NTLOG_INT("paint: pthread_create ret=", ret);
    return 0;
}
