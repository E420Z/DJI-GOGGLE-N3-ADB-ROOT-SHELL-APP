/* n3app.c — framework implementation for the N3 app SDK. */
#define NTLOG_PREFIX "n3app"
#include "natartos_common.h"
#include "n3app.h"

#define __NR_unlinkat 35
#define __NR_ioctl 29
#define O_NONBLOCK 0x800
#define O_EXCL 0200

/* _IOW('E', 0x90, int) */
#define EVIOCGRAB 0x40044590UL

/* Off until a single, correctly-typed DisplayEngine hook is verified. The
 * three-overload hook caused a black screen on 2026-11-25. */
#ifndef N3_ENABLE_DISPLAY_HOOKS
#define N3_ENABLE_DISPLAY_HOOKS 0
#endif

static inline long sys_ioctl(int fd, unsigned long req, unsigned long arg) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = req;
    register long x2 __asm__("x2") = arg;
    register long x8 __asm__("x8") = __NR_ioctl;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

#define EV_SYN 0
#define EV_KEY 1
#define EV_ABS 3

#define BTN_TOUCH 330
#define ABS_X 0
#define ABS_Y 1
#define ABS_MT_POSITION_X 53
#define ABS_MT_POSITION_Y 54
#define ABS_MT_TRACKING_ID 57

#define TOUCH_DEV "/dev/input/event1"
#define TOUCH_LOG_FLAG "/data/local/tmp/n3_touch_log"
#define SWIPE_MIN 40

struct input_event_t { long sec, usec; unsigned short type, code; int value; };

static int g_t_down, g_t_btn_seen;
static int g_t_sx, g_t_sy, g_t_lx, g_t_ly;

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

/* ---- Atomic entry-point detour (same proven scheme as capture-mod) ---- */
#define PROT_EXEC 4
#define __NR_mmap 222
#define __NR_munmap 215
#define MAP_PRIVATE 2
#define MAP_ANONYMOUS 0x20
#define MAP_FAILED ((void *)-1)
#define MAP_FIXED_NOREPLACE 0x100000

static void *sys_mmap(void *addr, long len, int prot, int flags, int fd, long off) {
    register long x0 __asm__("x0") = (long)addr;
    register long x1 __asm__("x1") = len;
    register long x2 __asm__("x2") = prot;
    register long x3 __asm__("x3") = flags;
    register long x4 __asm__("x4") = fd;
    register long x5 __asm__("x5") = off;
    register long x8 __asm__("x8") = __NR_mmap;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
    return (void *)x0;
}

static long sys_munmap(void *addr, long len) {
    register long x0 __asm__("x0") = (long)addr;
    register long x1 __asm__("x1") = len;
    register long x8 __asm__("x8") = __NR_munmap;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return x0;
}

static void flush_icache(void *addr, long size) {
    unsigned long p = (unsigned long)addr & ~63UL;
    unsigned long end = (unsigned long)addr + size;
    for (; p < end; p += 64) __asm__ volatile("dc cvau, %0" :: "r"(p) : "memory");
    __asm__ volatile("dsb ish" ::: "memory");
    p = (unsigned long)addr & ~63UL;
    for (; p < end; p += 64) __asm__ volatile("ic ivau, %0" :: "r"(p) : "memory");
    __asm__ volatile("dsb ish" ::: "memory");
    __asm__ volatile("isb" ::: "memory");
}

static void *try_stub_at(unsigned long near, long off) {
    unsigned long hint = (near + off) & ~0xFFFUL;
    void *p = sys_mmap((void *)hint, 0x1000, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (p == MAP_FAILED) return 0;
    long got = (long)((unsigned long)p - near);
    if (got > -0x7000000L && got < 0x7000000L) return p;
    sys_munmap(p, 0x1000);
    return 0;
}

static void *map_stub_near(unsigned long near) {
    /* Fine scan close to the target, where small gaps usually exist. */
    for (long off = -0x1000000L; off <= 0x1000000L; off += 0x1000L) {
        if (off == 0) continue;
        void *p = try_stub_at(near, off);
        if (p) return p;
    }
    /* Coarser scan over the rest of the +/-112 MB branch range. */
    for (long off = -0x7000000L; off <= 0x7000000L; off += 0x10000L) {
        if (off >= -0x1000000L && off <= 0x1000000L) continue;
        void *p = try_stub_at(near, off);
        if (p) return p;
    }
    return 0;
}

static int insn_pc_relative(unsigned int i) {
    if ((i & 0x1F000000) == 0x10000000) return 1; /* adr/adrp */
    if ((i & 0x7C000000) == 0x14000000) return 1; /* b/bl */
    if ((i & 0x3B000000) == 0x18000000) return 1; /* ldr literal */
    if ((i & 0x7E000000) == 0x34000000) return 1; /* cbz/cbnz */
    if ((i & 0x3E000000) == 0x36000000) return 1; /* tbz/tbnz */
    return 0;
}

/* Returns a call-original trampoline, or 0 on failure. */
static void *install_hook(void *target, void *hook) {
    unsigned int *t = (unsigned int *)target;
    unsigned int insn0 = t[0];
    if (insn_pc_relative(insn0)) {
        NTLOG("hook: first insn PC-relative; refusing");
        return 0;
    }
    void *stub = map_stub_near((unsigned long)target);
    if (!stub) { NTLOG("hook: no stub page in range"); return 0; }
    unsigned int *s = (unsigned int *)stub;
    int i = 0;
    void *call_orig = &s[i];
    s[i++] = insn0;
    s[i++] = 0x58000050;
    s[i++] = 0xD61F0200;
    *(unsigned long *)&s[i] = (unsigned long)target + 4; i += 2;
    unsigned int *veneer = &s[i];
    s[i++] = 0x58000050;
    s[i++] = 0xD61F0200;
    *(unsigned long *)&s[i] = (unsigned long)hook; i += 2;
    sys_mprotect(stub, 0x1000, PROT_READ | PROT_EXEC);
    flush_icache(stub, i * 4);
    long off = (long)((unsigned long)veneer - (unsigned long)target);
    if (off <= -0x8000000L || off >= 0x8000000L) { NTLOG("hook: veneer out of range"); return 0; }
    unsigned int b = 0x14000000u | ((unsigned int)(off >> 2) & 0x03FFFFFFu);
    unsigned long page = (unsigned long)target & ~0xFFFUL;
    if (sys_mprotect((void *)page, 0x2000, PROT_READ | PROT_WRITE | PROT_EXEC) < 0) {
        NTLOG("hook: mprotect failed"); return 0;
    }
    __atomic_store_n(t, b, __ATOMIC_RELEASE);
    flush_icache(target, 4);
    return call_orig;
}

typedef int (*push_fn_t)(void *, int, void *);
typedef int (*key_fn_t)(void *, int, int, int);
typedef int (*bsp_get_fn)(void *);
typedef long (*fn6_t)(void *, void *, void *, void *, void *, void *);
static push_fn_t g_real_push;
static key_fn_t g_real_key;
static bsp_get_fn g_real_bsp_key, g_real_bsp_touch;
static fn6_t g_real_key_proc, g_real_touch_proc;
static fn6_t g_real_disp_vsync, g_real_disp_df1, g_real_disp_df5;
static int g_push_hooked, g_key_hooked, g_bsp_key, g_bsp_touch;

/* Optional menu toggle key: /data/local/tmp/n3_menu_toggle contains
 * "<event> <keycode>" (e.g. "3 116") or just "<keycode>". A short tap toggles
 * the menu; a long hold is left to the stock power handler. */
#define TOGGLE_CFG "/data/local/tmp/n3_menu_toggle"
static const char *EV_PATHS[4] = {
    "/dev/input/event0", "/dev/input/event1",
    "/dev/input/event2", "/dev/input/event3"
};
static int g_toggle_key, g_toggle_ev = 3;
static long g_toggle_ms;
static long g_up_ms;

#define FRAME_W 1920
#define FRAME_H 1080
#define FRAME_SIZE (FRAME_W * FRAME_H * 4)

#define FLAG_ON   "/data/local/tmp/n3_app_on"
#define FLAG_EXIT "/data/local/tmp/n3_app_exit"
#define MAPS_PATH "/proc/self/maps"

#define N3_MAX_W 1200
#define N3_MAX_H 960
#define DEF_X 560
#define DEF_Y 360
#define DEF_W 800
#define DEF_H 340

#define TITLE_H 46
#define INSET   10

static const n3_app *g_app;
static void hide_app(void);
static unsigned long g_fbs[4];
static int g_fb_count;
static long g_last_scan_ms;
static int g_prev_on;
static unsigned int g_frame;

static unsigned int g_backup[2][N3_MAX_W * N3_MAX_H];
static int g_have_backup[2];

/* Double-buffered offscreen canvas: app draws into the back buffer, then
 * publishes it; the push hook reads only the published front buffer. */
static unsigned int g_canvas[2][N3_MAX_W * N3_MAX_H];
static volatile int g_front;
static int g_grab0, g_grab1, g_grab0_fail, g_grab1_fail;
static long g_k_up_ms, g_k_down_ms;
static int g_logged_draw, g_logged_push, g_push_calls;

static int g_x, g_y, g_w, g_h;   /* window rect */

static const n3_color C_BG     = 0xFF1E1E1E;
static const n3_color C_BORDER = 0xFF3A3A3A;
static const n3_color C_TITLE  = 0xFF1E1E1E;
static const n3_color C_TEXT   = 0xFFFFFFFF;
static const n3_color C_DIM    = 0xFFB0B0B0;

/* ------------------------------------------------------------------ utils */

static long now_ms(void) {
    struct timespec_t t;
    register long x0 __asm__("x0") = 1;
    register long x1 __asm__("x1") = (long)&t;
    register long x8 __asm__("x8") = 113;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return (long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int iabs(int v) { return v < 0 ? -v : v; }

static int word_is(const char *s, const char *w) {
    int i = 0;
    while (w[i]) { if (s[i] != w[i]) return 0; i++; }
    char c = s[i];
    return c == 0 || c == '\n' || c == '\r' || c == ' ' || c == '\t';
}

static void log3(const char *a, int v1, int v2, int v3) {
    char buf[96];
    int i = 0;
    const char *p = a;
    while (*p && i < 40) buf[i++] = *p++;
    int vals[3] = { v1, v2, v3 };
    for (int k = 0; k < 3; k++) {
        buf[i++] = ' ';
        int v = vals[k];
        if (v < 0) { buf[i++] = '-'; v = -v; }
        char d[12]; int n = 0;
        if (v == 0) d[n++] = '0';
        while (v > 0) { d[n++] = (char)('0' + v % 10); v /= 10; }
        while (n > 0) buf[i++] = d[--n];
    }
    buf[i] = 0;
    natartos_log_raw(NTLOG_PREFIX, buf);
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
        char c = *s; int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else break;
        v = (v << 4) | (unsigned)d; s++;
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

static inline void spx(n3_surface *s, int x, int y, n3_color c) {
    if (x < 0 || x >= s->w || y < 0 || y >= s->h) return;
    s->pixels[(long)y * s->stride + x] = c;
}

void n3_fill(n3_surface *s, int x, int y, int w, int h, n3_color c) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            spx(s, x + i, y + j, c);
}

void n3_frame_rect(n3_surface *s, int x, int y, int w, int h, int t, n3_color c) {
    n3_fill(s, x, y, w, t, c);
    n3_fill(s, x, y + h - t, w, t, c);
    n3_fill(s, x, y, t, h, c);
    n3_fill(s, x + w - t, y, t, h, c);
}

/* 5x7 font, 7 row bytes per glyph. */
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
    static const unsigned char eq[7]  = {0,0,0x1F,0,0x1F,0,0};
    static const unsigned char dash[7]= {0,0,0,0x0E,0,0,0};
    static const unsigned char dot[7] = {0,0,0,0,0,0x0C,0x0C};
    static const unsigned char colon[7]={0,0x0C,0x0C,0,0x0C,0x0C,0};
    static const unsigned char slash[7]={0x01,0x02,0x02,0x04,0x08,0x08,0x10};
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
    case '=': return eq; case '-': return dash; case '.': return dot;
    case ':': return colon; case '/': return slash;
    default:  return sp;
    }
}

int n3_text_width(const char *text, int scale) {
    int n = 0;
    while (text[n]) n++;
    return n * 6 * scale;
}

void n3_text(n3_surface *s, int x, int y, const char *text, int scale, n3_color c) {
    for (int k = 0; text[k]; k++) {
        const unsigned char *g = glyph(text[k]);
        int ox = x + k * 6 * scale;
        for (int r = 0; r < 7; r++) {
            unsigned char row = g[r];
            for (int col = 0; col < 5; col++) {
                if (row & (1 << (4 - col)))
                    n3_fill(s, ox + col * scale, y + r * scale, scale, scale, c);
            }
        }
    }
}

/* --------------------------------------------------------------- framework */

static void save_region(unsigned int *base, int slot) {
    if (g_have_backup[slot]) return;
    for (int j = 0; j < g_h; j++)
        for (int i = 0; i < g_w; i++)
            g_backup[slot][j * N3_MAX_W + i] =
                base[(long)(g_y + j) * FRAME_W + (g_x + i)];
    g_have_backup[slot] = 1;
}

static void restore_region(unsigned int *base, int slot) {
    if (!g_have_backup[slot]) return;
    for (int j = 0; j < g_h; j++)
        for (int i = 0; i < g_w; i++)
            base[(long)(g_y + j) * FRAME_W + (g_x + i)] =
                g_backup[slot][j * N3_MAX_W + i];
    g_have_backup[slot] = 0;
}

static void draw_window(unsigned int *canvas) {
    n3_surface win = { canvas, g_w, g_h, g_w };

    n3_fill(&win, 0, 0, g_w, g_h, C_BG);
    n3_frame_rect(&win, 0, 0, g_w, g_h, 1, C_BORDER);
    n3_fill(&win, 1, 1, g_w - 2, TITLE_H, C_TITLE);
    {
        const char *nm = g_app->name ? g_app->name : "N3 APP";
        int tw = n3_text_width(nm, 3);
        n3_text(&win, (g_w - tw) / 2, 1 + (TITLE_H - 18) / 2,
                nm, 3, C_TEXT);
        n3_fill(&win, 1, 1 + TITLE_H, g_w - 2, 1, C_BORDER);
    }

    n3_surface app = {
        canvas + (long)(TITLE_H + INSET) * g_w + INSET,
        g_w - 2 * INSET,
        g_h - TITLE_H - 2 * INSET - 26,
        g_w
    };
    if (g_app->on_tick) g_app->on_tick(&app, g_frame);

    {
        const char *hint = "UP/DOWN MOVE   CENTER OK   BACK EXIT";
        int tw = n3_text_width(hint, 2);
        n3_text(&win, (g_w - tw) / 2, g_h - 22, hint, 2, C_DIM);
    }
}

static void blit_window(unsigned int *base, const unsigned int *canvas) {
    for (int j = 0; j < g_h; j++) {
        unsigned int *d = base + (long)(g_y + j) * FRAME_W + g_x;
        const unsigned int *s = canvas + (long)j * g_w;
        for (int i = 0; i < g_w; i++) d[i] = s[i];
    }
}

static int g_disp_calls;

static void composite_now(void) {
    if (g_fb_count <= 0) return;
    if (!g_logged_push) { NTLOG_INT("composite: fbs=", g_fb_count); g_logged_push = 1; }
    const unsigned int *c = g_canvas[g_front];
    unsigned int *b0 = (unsigned int *)g_fbs[0];
    save_region(b0, 0);
    blit_window(b0, c);
    if (g_fb_count > 1) {
        unsigned int *b1 = (unsigned int *)g_fbs[1];
        save_region(b1, 1);
        blit_window(b1, c);
    }
}

/* Called on the UI thread from the push detour: publish our window last. */
static int push_hook(void *display, int plane, void *frame_buf) {
    if (g_push_calls++ == 0) NTLOG("push: called");
    if (sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) == 0) composite_now();
    if (g_real_push) return g_real_push(display, plane, frame_buf);
    return 0;
}

/* EwAddons::DisplayEngine::displayFrame* — the real per-frame present path.
 * C++ member function: x0 = this, x1.. = args. Each target needs its own
 * trampoline so the correct original is called. */
#if N3_ENABLE_DISPLAY_HOOKS
#define DISP_HOOK(name, real) \
    static long name(void *a, void *b, void *c, void *d, void *e, void *f) { \
        if (g_disp_calls++ == 0) NTLOG("displayFrame: called"); \
        if (sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) == 0) composite_now(); \
        return real ? real(a, b, c, d, e, f) : 0; \
    }

DISP_HOOK(disp_vsync_hook, g_real_disp_vsync)
DISP_HOOK(disp_df1_hook, g_real_disp_df1)
DISP_HOOK(disp_df5_hook, g_real_disp_df5)
#endif

/* Called by the UI's key dispatch: consume keys while our app is open.
 *
 * The N3's two buttons arrive as EW UP (key 1) and EW DOWN (key 2), not OK/EXIT.
 * A short press navigates; a long hold (>=700 ms) selects (DOWN) or exits (UP).
 */
static int key_hook(void *root, int key, int ch, int down) {
    int handled = (key == 1 || key == 2 || key == 3 || key == 4 ||
                   key == 6 || key == 18 || key == 19);
    if (sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) != 0) {
        if (g_real_key) return g_real_key(root, key, ch, down);
        return 0;
    }
    /* Swallow every key while the app is open, even unknown codes, so no stock
     * panel/bar can open from a key.  Always pass key-up events through: the
     * stock UI saw the matching down before the page opened, and swallowing
     * the up leaves its key state stuck (the sidebar then refuses to reopen
     * after the page closes). */
    if (!handled) return 0;
    if (!down) {
        if (g_real_key) return g_real_key(root, key, ch, 0);
        return 0;
    }
    log3("key", key, down, ch);

    /* Directions are handled once, by the event3 reader (down events are
     * reliable; CoreRoot does not always deliver the matching release). */
    if (key == 1 || key == 2 || key == 3 || key == 4) return 0;

    if (down) {
        switch (key) {
        case 6: if (g_app->on_key) g_app->on_key(N3_KEY_ENTER); break;
        case 19:
            if (g_app->on_key) g_app->on_key(N3_KEY_BACK);
            if (!g_app->manual_back) hide_app();
            break;
        case 18: break;
        }
    }
    return 0;
}

static void hide_app(void) {
    sys_unlinkat(AT_FDCWD, FLAG_ON, 0);
    int x = (int)sys_openat(AT_FDCWD, FLAG_EXIT,
                            O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (x >= 0) sys_close(x);
    if (g_app->on_close) g_app->on_close();
    g_t_down = 0;
    NTLOG("hide");
}

void n3_hide(void) { hide_app(); }

static void finish_touch(void) {
    int dx = g_t_lx - g_t_sx;
    int dy = g_t_ly - g_t_sy;
    g_t_down = 0;
    if (iabs(dy) >= SWIPE_MIN && iabs(dy) >= iabs(dx)) {
        log3("swipe dx dy", dx, dy, 0);
        if (g_app->on_swipe) g_app->on_swipe(0, dy);
    } else {
        log3("tap x y", g_t_sx, g_t_sy, 0);
        if (g_app->on_tap) g_app->on_tap(g_t_sx, g_t_sy);
    }
}

static int app_active(void) {
    return sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) == 0;
}

/* BSP consumers used by Embedded Wizard. Returning 0 means "no event", so the
 * stock UI processes neither keys nor touch while our app is open. Our app
 * reads the raw /dev/input devices directly. */
static int bsp_key_hook(void *arg) {
    /* Always let the BSP advance its 5D/ADC state.  Suppression happens at the
     * final CoreRoot dispatch (key_hook), otherwise the stock UI is left with a
     * stuck 5D value and the sidebar will not reopen after the page closes. */
    return g_real_bsp_key ? g_real_bsp_key(arg) : 0;
}

static int bsp_touch_hook(void *arg) {
    if (app_active()) return 0;
    return g_real_bsp_touch ? g_real_bsp_touch(arg) : 0;
}

/* EW's platform event processors. Skipping these stops the stock UI from
 * seeing any key or touch while our app is open. */
static long key_proc_hook(void *a, void *b, void *c, void *d, void *e, void *f) {
    /* Pass through (see bsp_key_hook): key_hook does the actual suppression. */
    return g_real_key_proc ? g_real_key_proc(a, b, c, d, e, f) : 0;
}

static long touch_proc_hook(void *a, void *b, void *c, void *d, void *e, void *f) {
    if (app_active()) return 0;
    return g_real_touch_proc ? g_real_touch_proc(a, b, c, d, e, f) : 0;
}

static void read_toggle_cfg(void) {
    int fd = (int)sys_openat(AT_FDCWD, TOGGLE_CFG, O_RDONLY, 0);
    if (fd < 0) { g_toggle_key = 0; return; }
    char b[64];
    long n = sys_read(fd, b, sizeof(b) - 1);
    sys_close(fd);
    if (n <= 0) { g_toggle_key = 0; return; }
    b[n] = 0;
    int nums[2] = { 0, 0 }, cnt = 0, v = 0, have = 0;
    for (int i = 0; i <= n; i++) {
        char c = i < n ? b[i] : ' ';
        if (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); have = 1; }
        else if (have) { if (cnt < 2) nums[cnt] = v; cnt++; v = 0; have = 0; }
    }
    if (cnt == 1) { g_toggle_ev = 3; g_toggle_key = nums[0]; }
    else if (cnt >= 2) { g_toggle_ev = nums[0]; g_toggle_key = nums[1]; }
    else { g_toggle_key = 0; }
    if (g_toggle_ev < 0 || g_toggle_ev > 3) g_toggle_ev = 3;
}

static void menu_toggle(void) {
    if (app_active()) {
        hide_app();
        NTLOG("up toggle hide");
    } else {
        int x = (int)sys_openat(AT_FDCWD, FLAG_ON,
                                O_WRONLY | O_CREAT | O_EXCL, 0666);
        if (x >= 0) {
            sys_close(x);
            NTLOG("up toggle show");
        }
    }
}

static void *app_thread_fn(void *arg) {
    (void)arg;
    NTLOG("thread: start");
    struct timespec_t ts = { 0, 33000000 }; /* 30 fps blit */
    int fd = -1, tfd = -1, pfd = -1, wfd = -1, last_ev = -1;
    long last_toggle_cfg = 0;
    while (1) {
        long ms = now_ms();
        if (ms - last_toggle_cfg > 2000) {
            read_toggle_cfg();
            last_toggle_cfg = ms;
        }
        if (ms - g_last_scan_ms > 2000) {
            g_fb_count = find_dmabufs();
            g_last_scan_ms = ms;
        }

        int on = sys_faccessat(AT_FDCWD, FLAG_ON, F_OK) == 0;
        if (on && !g_prev_on) NTLOG("show");
        /* Freeze painting while the capture hook is taking a screenshot, so
         * the read frame is always a complete one (no mid-draw sliver). */
        int capturing = sys_faccessat(AT_FDCWD, "/data/local/tmp/n3_capture", F_OK) == 0;
        if (on && g_fb_count > 0 && !capturing) {
            if (!g_logged_draw) { NTLOG_INT("draw: fbs=", g_fb_count); g_logged_draw = 1; }
            if (!g_prev_on && g_app->on_open) g_app->on_open(0);
            int back = 1 - g_front;
            draw_window(g_canvas[back]);
            __atomic_store_n(&g_front, back, __ATOMIC_RELEASE);
            const unsigned int *c = g_canvas[g_front];
            unsigned int *fb0 = (unsigned int *)g_fbs[0];
            save_region(fb0, 0);
            blit_window(fb0, c);
            if (g_fb_count > 1) {
                unsigned int *fb1 = (unsigned int *)g_fbs[1];
                save_region(fb1, 1);
                blit_window(fb1, c);
            }
            g_frame++;
        } else if (!on && g_prev_on) {
            for (int i = 0; i < g_fb_count && i < 2; i++)
                restore_region((unsigned int *)g_fbs[i], i);
            g_frame = 0;
            NTLOG("restore");
        }
        g_prev_on = on;

        if (fd < 0)
            fd = (int)sys_openat(AT_FDCWD, "/dev/input/event0",
                                 O_RDONLY | O_NONBLOCK, 0);
        if (fd >= 0) {
            /* Exclusively grab BACK/ENTER while the app is open so the stock
             * UI does not also react to the same button presses. */
            if (on && !g_grab0 && !g_grab0_fail) {
                long r = sys_ioctl(fd, EVIOCGRAB, 1);
                if (r == 0) { g_grab0 = 1; NTLOG("grab event0 ok"); }
                else { g_grab0_fail = 1; NTLOG_INT("grab event0 FAIL=", (int)r); }
            } else if (!on && g_grab0) {
                sys_ioctl(fd, EVIOCGRAB, 0);
                g_grab0 = 0; g_grab0_fail = 0;
                NTLOG("ungrab event0");
            }
            struct input_event_t ev;
            while (sys_read(fd, &ev, sizeof(ev)) == (long)sizeof(ev)) {
                if (g_key_hooked || ev.type != EV_KEY) continue;
                if (ev.code == 28) {
                    log3("raw key", ev.code, ev.value, 0);
                    if (ev.value == 1 && on && g_app->on_key)
                        g_app->on_key(N3_KEY_ENTER);
                    continue;
                }
                if (!on) continue;
                if (g_toggle_ev == 0 && ev.code == g_toggle_key) continue;
                if (ev.code == 158) {
                    log3("raw key", ev.code, ev.value, 0);
                    if (ev.value == 1) {
                        if (g_app->on_key) g_app->on_key(N3_KEY_BACK);
                        if (!g_app->manual_back) hide_app();
                    }
                }
            }
        }

        /* 5-way directions (omc_keys / event3). */
        if (wfd < 0)
            wfd = (int)sys_openat(AT_FDCWD, "/dev/input/event3",
                                  O_RDONLY | O_NONBLOCK, 0);
        if (wfd >= 0) {
            struct input_event_t ev;
            while (sys_read(wfd, &ev, sizeof(ev)) == (long)sizeof(ev)) {
                if (ev.type != EV_KEY) continue;
                if (ev.value != 1 || !on) continue;
                if (ev.code == 103) {
                    if (g_app->on_swipe) g_app->on_swipe(0, 100);
                    NTLOG("5way up");
                } else if (ev.code == 108) {
                    if (g_app->on_swipe) g_app->on_swipe(0, -100);
                    NTLOG("5way down");
                } else if (ev.code == 105) {
                    if (g_app->on_swipe) g_app->on_swipe(-100, 0);
                    NTLOG("5way left");
                } else if (ev.code == 106) {
                    if (g_app->on_swipe) g_app->on_swipe(100, 0);
                    NTLOG("5way right");
                }
            }
        }

        /* Optional power-tap menu toggle (read-only; no grab). */
        if (g_toggle_key) {
            if (pfd >= 0 && last_ev != g_toggle_ev) {
                sys_close(pfd);
                pfd = -1;
            }
            if (pfd < 0) {
                pfd = (int)sys_openat(AT_FDCWD, EV_PATHS[g_toggle_ev],
                                      O_RDONLY | O_NONBLOCK, 0);
                last_ev = g_toggle_ev;
            }
            if (pfd >= 0) {
                struct input_event_t ev;
                while (sys_read(pfd, &ev, sizeof(ev)) == (long)sizeof(ev)) {
                    if (ev.type != EV_KEY || ev.code != g_toggle_key) continue;
                    if (ev.value == 1) {
                        g_toggle_ms = now_ms();
                    } else if (ev.value == 0) {
                        long held = now_ms() - g_toggle_ms;
                        if (held > 0 && held < 600) {
                            if (on) {
                                hide_app();
                                NTLOG("toggle hide");
                            } else {
                                int x = (int)sys_openat(AT_FDCWD, FLAG_ON,
                                            O_WRONLY | O_CREAT | O_EXCL, 0666);
                                if (x >= 0) {
                                    sys_close(x);
                                    NTLOG("toggle show");
                                }
                            }
                        }
                    }
                }
            }
        } else if (pfd >= 0) {
            sys_close(pfd);
            pfd = -1;
        }

        /* Touchpad (ext_touch). Raw deltas: swipe for lists, tap to select. */
        if (tfd < 0)
            tfd = (int)sys_openat(AT_FDCWD, TOUCH_DEV,
                                  O_RDONLY | O_NONBLOCK, 0);
        if (tfd >= 0) {
            if (on && !g_grab1 && !g_grab1_fail) {
                long r = sys_ioctl(tfd, EVIOCGRAB, 1);
                if (r == 0) { g_grab1 = 1; NTLOG("grab event1 ok"); }
                else { g_grab1_fail = 1; NTLOG_INT("grab event1 FAIL=", (int)r); }
            } else if (!on && g_grab1) {
                sys_ioctl(tfd, EVIOCGRAB, 0);
                g_grab1 = 0; g_grab1_fail = 0;
                NTLOG("ungrab event1");
            }
            int logt = sys_faccessat(AT_FDCWD, TOUCH_LOG_FLAG, F_OK) == 0;
            struct input_event_t ev;
            while (sys_read(tfd, &ev, sizeof(ev)) == (long)sizeof(ev)) {
                if (logt && ev.type != EV_SYN)
                    log3("touch type code value", ev.type, ev.code, ev.value);
                if (!on) continue;
                if (ev.type == EV_ABS) {
                    if (ev.code == ABS_MT_POSITION_X || ev.code == ABS_X)
                        g_t_lx = ev.value;
                    else if (ev.code == ABS_MT_POSITION_Y || ev.code == ABS_Y)
                        g_t_ly = ev.value;
                    else if (ev.code == ABS_MT_TRACKING_ID && !g_t_btn_seen) {
                        if (ev.value >= 0 && !g_t_down) {
                            g_t_down = 1; g_t_sx = g_t_lx; g_t_sy = g_t_ly;
                        } else if (ev.value < 0 && g_t_down) {
                            finish_touch();
                        }
                    }
                } else if (ev.type == EV_KEY && ev.code == BTN_TOUCH) {
                    g_t_btn_seen = 1;
                    if (ev.value == 1 && !g_t_down) {
                        g_t_down = 1; g_t_sx = g_t_lx; g_t_sy = g_t_ly;
                    } else if (ev.value == 0 && g_t_down) {
                        finish_touch();
                    }
                }
            }
        }
        /* Scriptable input for tests/host control. */
        if (sys_faccessat(AT_FDCWD, "/data/local/tmp/n3_input_cmd", F_OK) == 0) {
            char b[64];
            int cf = (int)sys_openat(AT_FDCWD, "/data/local/tmp/n3_input_cmd",
                                     O_RDONLY, 0);
            long n = cf >= 0 ? sys_read(cf, b, sizeof(b) - 1) : 0;
            if (cf >= 0) sys_close(cf);
            sys_unlinkat(AT_FDCWD, "/data/local/tmp/n3_input_cmd", 0);
            if (n > 0) {
                b[n] = 0;
                NTLOG(b);
                if (on) {
                    if (word_is(b, "up") || word_is(b, "prev")) {
                        if (g_app->on_swipe) g_app->on_swipe(0, 100);
                    } else if (word_is(b, "down") || word_is(b, "next")) {
                        if (g_app->on_swipe) g_app->on_swipe(0, -100);
                    } else if (word_is(b, "ok")) {
                        if (g_app->on_key) g_app->on_key(N3_KEY_ENTER);
                    } else if (word_is(b, "back")) {
                        if (g_app->on_key) g_app->on_key(N3_KEY_BACK);
                        if (!g_app->manual_back) hide_app();
                    } else if (word_is(b, "hide")) {
                        hide_app();
                    }
                }
            }
        }
        sys_nanosleep(&ts, 0);
    }
    return 0;
}

int n3_start(const n3_app *app, void *(*loader_dlsym)(void *, const char *)) {
    g_app = app;
    g_dlsym = (dlsym_fn)loader_dlsym;

    g_w = app->w > 0 ? app->w : DEF_W;
    g_h = app->h > 0 ? app->h : DEF_H;
    if (g_w > N3_MAX_W) g_w = N3_MAX_W;
    if (g_h > N3_MAX_H) g_h = N3_MAX_H;
    if (g_w < 200) g_w = 200;
    if (g_h < 120) g_h = 120;
    g_x = app->x > 0 ? app->x : (FRAME_W - g_w) / 2;
    g_y = app->y > 0 ? app->y : (FRAME_H - g_h) / 2;
    if (g_x < 0) g_x = 0;
    if (g_y < 0) g_y = 0;
    if (g_x + g_w > FRAME_W) g_x = FRAME_W - g_w;
    if (g_y + g_h > FRAME_H) g_y = FRAME_H - g_h;

    /* The loader resolves push_frame from libdisp_eng only for (void*)-1. */
    void *push = g_dlsym ? g_dlsym((void *)-1, "duss_hal_display_push_frame") : 0;
    if (push) {
        NTLOG_HEX("push target=", (unsigned long)push);
        void *tr = install_hook(push, (void *)push_hook);
        if (tr) { g_real_push = (push_fn_t)tr; g_push_hooked = 1; NTLOG("push hook ok"); }
        else NTLOG("push hook failed");
    } else {
        NTLOG("push_frame not found");
    }

#if N3_ENABLE_DISPLAY_HOOKS
    /* Resolve libdisp_eng and hook the per-frame DisplayEngine present path. */
    {
        typedef void *(*dlopen_t)(const char *, int);
        typedef void *(*dlsym_t)(void *, const char *);
        dlopen_t pdlopen = g_dlsym ? (dlopen_t)g_dlsym(RTLD_DEFAULT, "dlopen") : 0;
        dlsym_t pdlsym = g_dlsym ? (dlsym_t)g_dlsym(RTLD_DEFAULT, "dlsym") : 0;
        void *disp = 0;
        if (pdlopen) {
            disp = pdlopen("libdisp_eng.so", 2 | 4);
            if (!disp) disp = pdlopen("/system/lib64/libdisp_eng.so", 2 | 4);
            if (!disp) disp = pdlopen("/system/lib64/libdisp_eng.so", 2);
        }
        if (disp && pdlsym) {
            struct { const char *n; void *hook; fn6_t *real; } ds[3] = {
                {"_ZN8EwAddons13DisplayEngine21displayFrameWithVsyncEP17duss_frame_buffer",
                 (void *)disp_vsync_hook, &g_real_disp_vsync},
                {"_ZN8EwAddons13DisplayEngine12displayFrameEP17duss_frame_buffer",
                 (void *)disp_df1_hook, &g_real_disp_df1},
                {"_ZN8EwAddons13DisplayEngine12displayFrameEiaiiP17duss_frame_buffer",
                 (void *)disp_df5_hook, &g_real_disp_df5},
            };
            for (int i = 0; i < 3; i++) {
                void *fn = pdlsym(disp, ds[i].n);
                if (!fn) continue;
                void *tr = install_hook(fn, ds[i].hook);
                if (tr) { *ds[i].real = (fn6_t)tr; NTLOG("disp hook ok"); }
                else NTLOG("disp hook failed");
            }
        } else {
            NTLOG("disp handle unavailable");
        }
    }
#endif

    void *kp = g_dlsym ? g_dlsym(RTLD_DEFAULT, "EwBspKeyEventProcess") : 0;
    if (kp) {
        void *tr = install_hook(kp, (void *)key_proc_hook);
        if (tr) { g_real_key_proc = (fn6_t)tr; g_bsp_key = 1; NTLOG("key process hook ok"); }
        else NTLOG("key process hook failed");
    } else {
        NTLOG("EwBspKeyEventProcess not found");
    }

    void *tp = g_dlsym ? g_dlsym(RTLD_DEFAULT, "EwBspTouchEventProcess") : 0;
    if (tp) {
        void *tr = install_hook(tp, (void *)touch_proc_hook);
        if (tr) { g_real_touch_proc = (fn6_t)tr; g_bsp_touch = 1; NTLOG("touch process hook ok"); }
        else NTLOG("touch process hook failed");
    } else {
        NTLOG("EwBspTouchEventProcess not found");
    }

    /* Do not hook EwBspGetKeyCommand / EwBspGetTouchEvent: returning 0 from
     * those getters makes EW dereference NULL (tombstone 2026-11-26,
     * EwBspGetKeyCommand+104). The process hooks above suppress stock input
     * while the app is open; the app reads /dev/input directly. */

    /* Always hook the final CoreRoot dispatch.  The BSP hooks above are now
     * pass-through so the platform 5D/ADC state stays consistent; key_hook is
     * the single place that suppresses keys while our page is open. */
    {
        void *key = g_dlsym ? g_dlsym(RTLD_DEFAULT, "CoreRoot_DriveKeyboardHitting") : 0;
        if (key) {
            void *tr = install_hook(key, (void *)key_hook);
            if (tr) { g_real_key = (key_fn_t)tr; g_key_hooked = 1; NTLOG("key hook ok"); }
            else NTLOG("key hook failed");
        } else {
            NTLOG("key dispatch not found");
        }
    }

    NTLOG("init");
    pthread_create_fn pcreate =
        g_dlsym ? (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create") : 0;
    if (!pcreate) { NTLOG("no pthread_create"); return -1; }
    unsigned long tid;
    int ret = pcreate(&tid, 0, app_thread_fn, 0);
    NTLOG_INT("pthread_create ret=", ret);
    return ret == 0 ? 0 : -1;
}
