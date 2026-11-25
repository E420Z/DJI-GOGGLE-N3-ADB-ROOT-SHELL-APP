/*
 * n3live ??? live downscaled frame stream for USB debugging.
 *
 * Reads the live 1920x1080 dmabuf, downscales by an integer factor, and writes
 * header+frame to /data/local/tmp/n3live.fifo as non-blocking FIFO writes.
 * No display hook, no frame suppression. If no reader is connected the write
 * is dropped.
 *
 * Header: 'N3LV' + u16 w + u16 h + u32 seq (little-endian), then BGRA pixels.
 */
#define NTLOG_PREFIX "live"
#include "natartos_common.h"

#define O_NONBLOCK 0x800

#define FRAME_W 1920
#define FRAME_H 1080
#define FRAME_SIZE (FRAME_W * FRAME_H * 4)

/* Downscale by 8 -> 240x135. 60 fps * 129,600 B = 7.8 MB/s. */
#define OUT_W 160
#define OUT_H 90
#define SCALE 12

#define FIFO_PATH "/data/local/tmp/n3live.fifo"
#define MAPS_PATH "/proc/self/maps"
#define TICK_NS 16000000L   /* 60 fps */

static unsigned long g_fbs[4];
static int g_fb_count;
static long g_last_scan;

/* 3 header words + pixels, so the pixel area is 4-byte aligned. */
static unsigned int g_out[3 + OUT_W * OUT_H];
static unsigned int g_seq;

static long now_ms(void) {
    struct timespec_t t;
    register long x0 __asm__("x0") = 1;
    register long x1 __asm__("x1") = (long)&t;
    register long x8 __asm__("x8") = 113;
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

static int fb_blank(const unsigned int *fb) {
    for (int y = 0; y < FRAME_H; y += 120)
        for (int x = 0; x < FRAME_W; x += 160)
            if (fb[(long)y * FRAME_W + x]) return 0;
    return 1;
}

static void build_frame(void) {
    unsigned int *fb = (unsigned int *)g_fbs[0];
    if (g_fb_count > 1 && fb_blank(fb)) fb = (unsigned int *)g_fbs[1];

    char *h = (char *)g_out;
    h[0] = 'N'; h[1] = '3'; h[2] = 'L'; h[3] = 'V';
    *(unsigned short *)(h + 4) = OUT_W;
    *(unsigned short *)(h + 6) = OUT_H;
    *(unsigned int *)(h + 8) = ++g_seq;

    unsigned int *dst = g_out + 3;
    for (int y = 0; y < OUT_H; y++) {
        const unsigned int *row = fb + (long)(y * SCALE) * FRAME_W;
        for (int x = 0; x < OUT_W; x++)
            dst[(long)y * OUT_W + x] = row[x * SCALE];
    }
}

static void *live_thread_fn(void *arg) {
    (void)arg;
    NTLOG("thread: start");
    struct timespec_t ts = { 0, TICK_NS };
    int fd = -1;
    long last_log = 0;
    while (1) {
        long ms = now_ms();
        if (ms - g_last_scan > 2000) {
            g_fb_count = find_dmabufs();
            g_last_scan = ms;
        }
        if (fd < 0)
            fd = (int)sys_openat(AT_FDCWD, FIFO_PATH, O_WRONLY | O_NONBLOCK, 0);
        if (fd >= 0 && g_fb_count > 0) {
            build_frame();
            long n = sys_write_raw(fd, g_out, 12 + OUT_W * OUT_H * 4);
            if (n < 0) {
                sys_close(fd);
                fd = -1;
                if (ms - last_log > 5000) {
                    NTLOG("fifo write failed; waiting for reader");
                    last_log = ms;
                }
            }
        }
        sys_nanosleep(&ts, 0);
    }
    return 0;
}

typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);
typedef void *(*dlsym_fn)(void *, const char *);

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    dlsym_fn g_dlsym = (dlsym_fn)loader_dlsym;
    NTLOG("init");
    pthread_create_fn pcreate =
        g_dlsym ? (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create") : 0;
    if (!pcreate) { NTLOG("no pthread_create"); return -1; }
    unsigned long tid;
    int ret = pcreate(&tid, 0, live_thread_fn, 0);
    NTLOG_INT("pthread_create ret=", ret);
    return 0;
}

