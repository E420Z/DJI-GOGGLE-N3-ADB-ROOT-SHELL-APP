/*
 * fb_receiver - PC screen -> DJI Goggles N3 display, over the RNDIS link.
 *
 * Part of N3 ROOT. Reads length-prefixed JPEG frames from a TCP socket and
 * publishes them into /data/local/tmp/fb_shared, which hook_overlay.so injects
 * into the display (64-byte header, counter at 0, two BGRA slots).
 *
 * Safety:
 *   - writes only /data/local/tmp/{fb_shared,fb_override,fb_stop,fb_receiver.log}
 *   - publishes a neutral "waiting" frame BEFORE touching fb_override, so the
 *     first thing the goggles shows is never an uninitialised buffer
 *   - on SIGINT/SIGTERM it removes fb_override and touches fb_stop, which makes
 *     the hook stop injecting and repaint the live UI
 *
 * Protocol: [u32le jpeg_len][jpeg bytes] repeated. Any size up to 4 MiB.
 *
 * Build: zig cc -target aarch64-linux-gnu -static -O2 -o fb_receiver fb_receiver.c -lm
 */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO
#include "stb_image.h"

#define FB_W 1920
#define FB_H 1080
#define FB_SIZE ((long)FB_W * FB_H * 4)
#define SHM_HEADER 64
#define SHM_SIZE (SHM_HEADER + 2L * FB_SIZE)

#define SHM_PATH   "/data/local/tmp/fb_shared"
#define FLAG_PATH  "/data/local/tmp/fb_override"
#define STOP_PATH  "/data/local/tmp/fb_stop"
#define LOG_PATH   "/data/local/tmp/fb_receiver.log"
#define PORT 5570
#define MAX_FRAME (4 * 1024 * 1024)

static int g_shm_fd = -1;
static unsigned char *g_shm = NULL;
static volatile unsigned int *g_counter;
static unsigned char *g_pixels;
static volatile int g_stop = 0;

static void logmsg(const char *fmt, ...) {
    FILE *f = fopen(LOG_PATH, "a");
    if (f) {
        va_list ap;
        va_start(ap, fmt);
        vfprintf(f, fmt, ap);
        va_end(ap);
        fclose(f);
    }
}

static void on_signal(int sig) { (void)sig; g_stop = 1; }

static int shm_init(void) {
    g_shm_fd = open(SHM_PATH, O_RDWR | O_CREAT, 0666);
    if (g_shm_fd < 0) { logmsg("shm open: %s\n", strerror(errno)); return -1; }
    if (ftruncate(g_shm_fd, SHM_SIZE) < 0) { logmsg("ftruncate: %s\n", strerror(errno)); return -1; }
    g_shm = mmap(NULL, SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, g_shm_fd, 0);
    if (g_shm == MAP_FAILED) { logmsg("mmap: %s\n", strerror(errno)); return -1; }
    g_counter = (volatile unsigned int *)g_shm;
    g_pixels = g_shm + SHM_HEADER;
    return 0;
}

/* The slot the overlay is NOT reading right now. */
static unsigned char *back_slot(void) {
    unsigned int c = __atomic_load_n(g_counter, __ATOMIC_RELAXED);
    return g_pixels + (unsigned long)((c + 1) & 1u) * FB_SIZE;
}

/* Centre a w*h BGRA image in the 1920x1080 frame, letterboxed. */
static void blit_bgra(const unsigned char *src, int w, int h) {
    unsigned char *base = back_slot();
    memset(base, 0, FB_SIZE);
    if (w <= 0 || h <= 0) { __atomic_add_fetch(g_counter, 1, __ATOMIC_RELEASE); return; }
    float sx = (float)FB_W / w, sy = (float)FB_H / h;
    float s = sx < sy ? sx : sy;
    int dw = (int)(w * s), dh = (int)(h * s);
    if (dw > FB_W) dw = FB_W;
    if (dh > FB_H) dh = FB_H;
    int ox = (FB_W - dw) / 2, oy = (FB_H - dh) / 2;
    for (int dy = 0; dy < dh; dy++) {
        int syi = (int)((long)dy * h / dh);
        const unsigned char *row = src + (long)syi * w * 4;
        unsigned char *dst = base + ((long)(oy + dy) * FB_W + ox) * 4;
        for (int dx = 0; dx < dw; dx++) {
            const unsigned char *sp = row + (long)((int)((long)dx * w / dw)) * 4;
            dst[0] = sp[0]; dst[1] = sp[1]; dst[2] = sp[2]; dst[3] = 255;
            dst += 4;
        }
    }
    __atomic_add_fetch(g_counter, 1, __ATOMIC_RELEASE);
}

/* Neutral frame shown while no PC frames arrive. */
static void publish_idle(int pulse) {
    unsigned char *base = back_slot();
    for (long i = 0; i < FB_SIZE; i += 4) {
        base[i + 0] = 18; base[i + 1] = 14; base[i + 2] = 26; base[i + 3] = 255;
    }
    /* a soft bar so it is obvious injection is active but idle */
    int by = FB_H / 2 - 6, bw = 360 + (pulse % 8) * 30;
    int bx = (FB_W - bw) / 2;
    for (int y = by; y < by + 12; y++) {
        unsigned char *row = base + (long)y * FB_W * 4;
        for (int x = bx; x < bx + bw; x++) {
            unsigned char *p = row + (long)x * 4;
            p[0] = 150; p[1] = 90; p[2] = 220; p[3] = 255;
        }
    }
    __atomic_add_fetch(g_counter, 1, __ATOMIC_RELEASE);
}

static int read_full(int fd, void *buf, size_t n) {
    size_t got = 0;
    while (got < n && !g_stop) {
        ssize_t r = recv(fd, (char *)buf + got, n - got, 0);
        if (r == 0) return 0;
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        got += (size_t)r;
    }
    return got == n ? 1 : 0;
}

static int serve_client(int fd) {
    unsigned char *jpg = malloc(MAX_FRAME);
    unsigned char *rgba = malloc((size_t)FB_W * FB_H * 4);
    if (!jpg || !rgba) { free(jpg); free(rgba); return -1; }

    logmsg("client connected\n");
    unsigned long frames = 0;
    while (!g_stop) {
        uint32_t len = 0;
        int ok = read_full(fd, &len, 4);
        if (ok <= 0) break;
        if (len == 0 || len > MAX_FRAME) { logmsg("bad frame len %u\n", len); break; }
        if (read_full(fd, jpg, len) <= 0) break;

        int w = 0, h = 0, comp = 0;
        unsigned char *px = stbi_load_from_memory(jpg, (int)len, &w, &h, &comp, 3);
        if (!px) { logmsg("jpeg decode failed (%d bytes)\n", len); continue; }

        /* RGB -> BGRA */
        long n = (long)w * h;
        unsigned char *dst = rgba;
        for (long i = 0; i < n; i++) {
            dst[0] = px[i * 3 + 2];
            dst[1] = px[i * 3 + 1];
            dst[2] = px[i * 3 + 0];
            dst[3] = 255;
            dst += 4;
        }
        stbi_image_free(px);
        blit_bgra(rgba, w, h);
        frames++;
        if (frames == 1) logmsg("first frame %dx%d (%u bytes)\n", w, h, len);
        if (frames % 60 == 0) logmsg("frames %lu\n", frames);
    }
    logmsg("client gone after %lu frames\n", frames);
    free(jpg);
    free(rgba);
    return 0;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    if (shm_init() != 0) return 1;
    publish_idle(0);                 /* valid frame BEFORE anyone can inject */

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) { logmsg("socket: %s\n", strerror(errno)); return 1; }
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons(PORT);
    if (bind(srv, (struct sockaddr *)&a, sizeof(a)) < 0) {
        logmsg("bind %d: %s\n", PORT, strerror(errno));
        return 1;
    }
    listen(srv, 1);
    logmsg("listening on %d\n", PORT);

    /* enable injection only once a frame is ready */
    int fl = open(FLAG_PATH, O_CREAT | O_WRONLY, 0666);
    if (fl >= 0) close(fl);
    logmsg("fb_override set\n");

    while (!g_stop) {
        fd_set rf;
        FD_ZERO(&rf);
        FD_SET(srv, &rf);
        struct timeval tv = {0, 500000};
        int sel = select(srv + 1, &rf, NULL, NULL, &tv);
        if (sel <= 0) { publish_idle((int)(tv.tv_usec / 1000)); continue; }
        int c = accept(srv, NULL, NULL);
        if (c < 0) continue;
        serve_client(c);
        close(c);
        publish_idle(0);
    }

    logmsg("shutting down\n");
    unlink(FLAG_PATH);
    int st = open(STOP_PATH, O_CREAT | O_WRONLY, 0666);
    if (st >= 0) close(st);
    usleep(600000);
    unlink(STOP_PATH);
    close(srv);
    munmap(g_shm, SHM_SIZE);
    close(g_shm_fd);
    logmsg("bye\n");
    return 0;
}
