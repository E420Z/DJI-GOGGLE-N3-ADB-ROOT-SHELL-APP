/*
 * n3h264live - live H.264 receiver + vendor decoder probe (no display yet).
 *
 * Listens on TCP 5572 for [u32le len][Annex-B access unit] frames, feeds each
 * AU to OMX.dji.video_decoder.avc.ffmpeg with ENDOFFRAME, and reports decoded
 * frame count. Used to prove the low-latency PC -> goggles transport before the
 * NV12 -> BGRA -> fb_shared stage.
 */
#define NTLOG_PREFIX "hlive"
#include "natartos_common.h"

#include <OMX_Types.h>
#include <OMX_Core.h>
#include <OMX_Component.h>
#include <OMX_Video.h>
#include <OMX_Index.h>

typedef void *(*dlsym_fn)(void *, const char *);
typedef void *(*dlopen_fn)(const char *, int);
typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);

#define RTLD_NOW 2
#define ARM_PATH "/data/local/tmp/h264live_on"
#define STAT_PATH "/data/local/tmp/h264live.stat"
#define PORT 5572
#define MAX_AU (1024 * 1024)
#define FB_W 1920
#define FB_H 1080
#define FB_SIZE ((long)FB_W * FB_H * 4)
#define SHM_HEADER 64
#define SHM_SIZE (SHM_HEADER + 2L * FB_SIZE)
#define SHM_PATH "/data/local/tmp/fb_shared"
#define OVR_PATH "/data/local/tmp/fb_override"
#define HOLD_PATH "/data/local/tmp/fb_hold"
#define STOP_PATH "/data/local/tmp/fb_stop"

/* sockets */
#define __NR_socket      198
#define __NR_bind        200
#define __NR_listen      201
#define __NR_accept      202
#define __NR_setsockopt  208
#define __NR_fcntl       25
#define __NR_unlinkat    35
#define __NR_ftruncate   46
#define __NR_mmap        222

struct sockaddr_in_t {
    unsigned short sin_family;
    unsigned short sin_port;
    unsigned int sin_addr;
    unsigned char pad[8];
};
struct timeval_t { long tv_sec; long tv_usec; };

static inline long sys_socket(int d, int t, int p) {
    register long x0 __asm__("x0") = d; register long x1 __asm__("x1") = t;
    register long x2 __asm__("x2") = p; register long x8 __asm__("x8") = __NR_socket;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
static inline long sys_bind(int fd, void *a, int l) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = (long)a;
    register long x2 __asm__("x2") = l; register long x8 __asm__("x8") = __NR_bind;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
static inline long sys_listen(int fd, int n) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = n;
    register long x8 __asm__("x8") = __NR_listen;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return x0;
}
static inline long sys_accept(int fd) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = 0;
    register long x2 __asm__("x2") = 0; register long x8 __asm__("x8") = __NR_accept;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
static inline long sys_setsockopt(int fd, int lvl, int name, void *v, int l) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = lvl;
    register long x2 __asm__("x2") = name; register long x3 __asm__("x3") = (long)v;
    register long x4 __asm__("x4") = l; register long x8 __asm__("x8") = __NR_setsockopt;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory");
    return x0;
}
static inline long sys_fcntl(int fd, int cmd, long arg) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = cmd;
    register long x2 __asm__("x2") = arg; register long x8 __asm__("x8") = __NR_fcntl;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
static inline long sys_unlink(const char *p) {
    register long x0 __asm__("x0") = AT_FDCWD; register long x1 __asm__("x1") = (long)p;
    register long x2 __asm__("x2") = 0; register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
static inline long sys_ftruncate(int fd, long len) {
    register long x0 __asm__("x0") = fd; register long x1 __asm__("x1") = len;
    register long x8 __asm__("x8") = __NR_ftruncate;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return x0;
}
static inline void *sys_mmap(void *addr, long len, int prot, int flags, int fd, long off) {
    register long x0 __asm__("x0") = (long)addr; register long x1 __asm__("x1") = len;
    register long x2 __asm__("x2") = prot; register long x3 __asm__("x3") = flags;
    register long x4 __asm__("x4") = fd; register long x5 __asm__("x5") = off;
    register long x8 __asm__("x8") = __NR_mmap;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
    return (void *)x0;
}

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_comp;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_state_ok, g_err, g_eos;
static volatile int g_fill_calls, g_empty_calls, g_frames;
static volatile long g_bytes;
static int g_fd = -1;
static int g_display;
static void publish_nv12(const unsigned char *yuv);
static void display_stop(void);
static int display_init(void);
static OMX_BUFFERHEADERTYPE *g_ib[4], *g_ob[4];
static int g_ni, g_no;
static OMX_U32 g_in_port, g_out_port;
static long g_ts;

static void set_ver(OMX_PARAM_PORTDEFINITIONTYPE *pd) {
    pd->nSize = sizeof(*pd);
    pd->nVersion.s.nVersionMajor = 1;
    pd->nVersion.s.nVersionMinor = 0;
    pd->nVersion.s.nRevision = 0;
    pd->nVersion.s.nStep = 0;
}

static void put_stat(void) {
    char b[64]; int n = 0;
    const char *k = "frames="; while (*k) b[n++] = *k++;
    long x = g_frames; char t[16]; int m = 0;
    if (!x) t[m++] = '0';
    while (x) { t[m++] = (char)('0' + x % 10); x /= 10; }
    while (m) b[n++] = t[--m];
    b[n++] = '\n';
    int fd = (int)sys_openat(AT_FDCWD, STAT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) { sys_write_raw(fd, b, n); sys_close(fd); }
}

static OMX_ERRORTYPE on_event(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                              OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) g_state_ok = 1;
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event err=", (int)d1); }
    return OMX_ErrorNone;
}
static OMX_ERRORTYPE on_empty(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b; g_empty_calls++; return OMX_ErrorNone;
}
static OMX_ERRORTYPE on_fill(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    g_fill_calls++;
    if (b->nFilledLen) {
        g_frames++;
        g_bytes += (long)b->nFilledLen;
        if (g_display) publish_nv12(b->pBuffer + b->nOffset);
        if (g_frames <= 3) {
            NTLOG_INT("fill len=", (int)b->nFilledLen);
            NTLOG_INT("  flags=", (int)b->nFlags);
        }
        if (g_fd >= 0 && g_frames <= 8) {
            long off = 0;
            while (off < (long)b->nFilledLen) {
                long w = sys_write_raw(g_fd, b->pBuffer + b->nOffset + off,
                                       (long)b->nFilledLen - off);
                if (w <= 0) break;
                off += w;
            }
        }
        if ((g_frames % 60) == 0) put_stat();
    }
    if (b->nFlags & OMX_BUFFERFLAG_EOS) g_eos = 1;
    if (!g_eos) OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}
static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };

static void teardown(void) {
    if (g_display) { display_stop(); g_display = 0; }
    if (g_comp) {
        g_state_ok = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_state_ok; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        for (int i = 0; i < g_ni; i++) if (g_ib[i]) OMX_FreeBuffer(g_comp, g_in_port, g_ib[i]);
        for (int i = 0; i < g_no; i++) if (g_ob[i]) OMX_FreeBuffer(g_comp, g_out_port, g_ob[i]);
        if (g_free_handle) g_free_handle(g_comp);
        g_comp = 0;
    }
    if (g_fd >= 0) { sys_close(g_fd); g_fd = -1; }
    sys_unlink(ARM_PATH);
}

static int read_full(int fd, void *buf, int n) {
    int got = 0;
    while (got < n) {
        long r = sys_read(fd, (char *)buf + got, n - got);
        if (r <= 0) return got ? got : -1;
        got += (int)r;
    }
    return got;
}

/* ---- display: NV12 -> BGRA -> fb_shared -> hook_overlay --------------- */
static unsigned char *g_shm, *g_pixels;
static volatile unsigned int *g_counter;
static int g_tab;
static int gy[256], grv[256], ggu[256], ggv[256], gbu[256];

static int touch_file(const char *p) {
    int fd = (int)sys_openat(AT_FDCWD, p, O_WRONLY | O_CREAT, 0644);
    if (fd >= 0) { sys_close(fd); return 0; }
    return -1;
}

static void display_stop(void) {
    sys_unlink(OVR_PATH);
    touch_file(STOP_PATH);
}

static int display_init(void) {
    int fd = (int)sys_openat(AT_FDCWD, SHM_PATH, 2 | O_CREAT, 0666);
    if (fd < 0) { NTLOG("fb_shared open failed"); return -1; }
    if (sys_ftruncate(fd, SHM_SIZE) != 0) {
        NTLOG("fb_shared ftruncate failed"); sys_close(fd); return -1;
    }
    void *p = sys_mmap(0, SHM_SIZE, 3 /*RW*/, 1 /*SHARED*/, fd, 0);
    sys_close(fd);
    if ((long)p < 0 && (long)p > -4096) { NTLOG("fb_shared mmap failed"); return -1; }
    g_shm = (unsigned char *)p;
    g_counter = (volatile unsigned int *)g_shm;
    g_pixels = g_shm + SHM_HEADER;
    *g_counter = 0;
    sys_unlink(STOP_PATH);
    touch_file(OVR_PATH);
    touch_file(HOLD_PATH);
    return 0;
}

static inline unsigned char cl8(int v) {
    return v < 0 ? 0 : (v > 255 ? 255 : (unsigned char)v);
}

static void table_init(void) {
    for (int i = 0; i < 256; i++) {
        gy[i]  = (int)(1.164 * (i - 16) * 256.0);
        grv[i] = (int)(1.793 * (i - 128) * 256.0);
        ggu[i] = (int)(-0.213 * (i - 128) * 256.0);
        ggv[i] = (int)(-0.533 * (i - 128) * 256.0);
        gbu[i] = (int)(2.112 * (i - 128) * 256.0);
    }
}

static void publish_nv12(const unsigned char *yuv) {
    if (!g_shm) return;
    if (!g_tab) { table_init(); g_tab = 1; }
    unsigned int c = __atomic_load_n(g_counter, __ATOMIC_RELAXED);
    unsigned char *base = g_pixels + (unsigned long)((c + 1) & 1u) * FB_SIZE;
    const unsigned char *yp = yuv;
    const unsigned char *uv = yuv + (long)FB_W * FB_H;
    for (int y = 0; y < FB_H; y++) {
        const unsigned char *yr = yp + (long)y * FB_W;
        const unsigned char *ur = uv + (long)(y >> 1) * FB_W;
        unsigned char *dst = base + (long)y * FB_W * 4;
        for (int x = 0; x < FB_W; x += 2) {
            int c0 = gy[yr[x]], c1 = gy[yr[x + 1]];
            int u = ur[x], v = ur[x + 1];
            int rv = grv[v], gu = ggu[u], gv = ggv[v], bu = gbu[u];
            dst[0] = cl8((c0 + bu) >> 8);
            dst[1] = cl8((c0 + gu + gv) >> 8);
            dst[2] = cl8((c0 + rv) >> 8);
            dst[3] = 255;
            dst[4] = cl8((c1 + bu) >> 8);
            dst[5] = cl8((c1 + gu + gv) >> 8);
            dst[6] = cl8((c1 + rv) >> 8);
            dst[7] = 255;
            dst += 8;
        }
    }
    __atomic_add_fetch(g_counter, 1, __ATOMIC_RELEASE);
}

static void worker(void) {
    int waited = 0;
    while (waited < 1800) {
        if (sys_faccessat(AT_FDCWD, ARM_PATH, 0) == 0) break;
        struct timespec_t t = { 0, 100000000 }; sys_nanosleep(&t, 0); waited++;
    }
    if (waited >= 1800) return;
    NTLOG("armed");

    dlopen_fn pdl = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pds = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    void *core = pdl ? pdl("libOmxCore.so", RTLD_NOW) : 0;
    if (!core) { NTLOG("no core"); return; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))pds(core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        pds(core, "OMX_GetHandle");
    g_free_handle = (OMX_ERRORTYPE (*)(OMX_HANDLETYPE))pds(core, "OMX_FreeHandle");
    if (!init || !get) return;
    init();

    OMX_ERRORTYPE e = get(&g_comp, "OMX.dji.video_decoder.avc.ffmpeg", 0, &g_cbs);
    NTLOG_INT("handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) { g_comp = 0; return; }

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    g_in_port = 0; g_out_port = 1;
    for (OMX_U32 i = 0; i < 3; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone) continue;
        if (pd.eDir == OMX_DirInput) g_in_port = i; else g_out_port = i;
    }

    for (int p = 0; p < 2; p++) {
        OMX_U32 port = p == 0 ? g_in_port : g_out_port;
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        if (p == 0) {
            pd.format.video.nFrameWidth = 1920;
            pd.format.video.nFrameHeight = 1080;
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingAVC;
        } else {
            pd.format.video.nFrameWidth = 1920;
            pd.format.video.nFrameHeight = 1080;
            pd.format.video.nStride = 1920;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
        }
        pd.nBufferCountActual = 4;
        OMX_SetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT(p == 0 ? "in size=" : "out size=", (int)pd.nBufferSize);
        for (int i = 0; i < 4; i++) {
            OMX_BUFFERHEADERTYPE *bh = 0;
            if (OMX_AllocateBuffer(g_comp, &bh, port, 0, pd.nBufferSize) != OMX_ErrorNone) break;
            if (p == 0) g_ib[g_ni++] = bh; else g_ob[g_no++] = bh;
        }
    }
    NTLOG_INT("in bufs=", g_ni);
    NTLOG_INT("out bufs=", g_no);
    if (!g_ni || !g_no) { teardown(); return; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("idle=", g_state_ok);
    if (!g_state_ok) { teardown(); return; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("exec=", g_state_ok);
    if (!g_state_ok) { teardown(); return; }
    for (int i = 0; i < g_no; i++) OMX_FillThisBuffer(g_comp, g_ob[i]);

    g_display = (display_init() == 0);
    NTLOG_INT("display=", g_display);
    if (g_display) touch_file(HOLD_PATH);

    int lfd = (int)sys_socket(2, 1, 0);
    if (lfd < 0) { NTLOG("socket failed"); teardown(); return; }
    int one = 1;
    sys_setsockopt(lfd, 1, 2, &one, 4);
    struct sockaddr_in_t sa;
    for (unsigned i = 0; i < sizeof(sa); i++) ((unsigned char *)&sa)[i] = 0;
    sa.sin_family = 2;
    sa.sin_port = (unsigned short)((PORT >> 8) | ((PORT & 0xff) << 8));
    if (sys_bind(lfd, &sa, sizeof(sa)) != 0) { NTLOG("bind failed"); sys_close(lfd); teardown(); return; }
    sys_listen(lfd, 1);
    sys_fcntl(lfd, 4, 0x800);
    NTLOG("listening on 5572");

    int cfd = -1;
    while (!g_eos) {
        cfd = (int)sys_accept(lfd);
        if (cfd >= 0) break;
        if (sys_faccessat(AT_FDCWD, ARM_PATH, 0) != 0) { sys_close(lfd); teardown(); return; }
        struct timespec_t t = { 0, 50000000 }; sys_nanosleep(&t, 0);
    }
    if (cfd < 0) { sys_close(lfd); teardown(); return; }
    NTLOG("client connected");
    sys_setsockopt(cfd, 6, 1, &one, 4);
    int rcv = 256 * 1024;
    sys_setsockopt(cfd, 1, 8, &rcv, 4);

    static unsigned char au[MAX_AU];
    g_fd = (int)sys_openat(AT_FDCWD, "/data/local/tmp/h264live_out.nv12", 0x241, 0644);
    int in_i = 0, sent = 0;
    while (!g_eos) {
        unsigned int len = 0;
        if (read_full(cfd, &len, 4) != 4) break;
        if (len == 0 || len > MAX_AU) { NTLOG_INT("bad len=", (int)len); break; }
        if (read_full(cfd, au, (int)len) != (int)len) break;
        while ((sent - g_empty_calls) >= g_ni) { struct timespec_t t={0,2000000}; sys_nanosleep(&t,0); }
        OMX_BUFFERHEADERTYPE *ib = g_ib[in_i % g_ni];
        for (unsigned i = 0; i < len; i++) ib->pBuffer[i] = au[i];
        ib->nFilledLen = len;
        ib->nOffset = 0;
        ib->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
        ib->nTimeStamp = g_ts;
        g_ts += 16666;
        OMX_EmptyThisBuffer(g_comp, ib);
        in_i++; sent++;
    }
    NTLOG_INT("aus=", sent);
    NTLOG_INT("frames=", g_frames);
    NTLOG_INT("bytes=", (int)g_bytes);
    put_stat();
    sys_close(cfd);
    sys_close(lfd);
    teardown();
    NTLOG("done");
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    pthread_create_fn pc = (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!pc) return 1;
    unsigned long tid;
    pc(&tid, 0, (void *(*)(void *))worker, 0);
    return 0;
}
