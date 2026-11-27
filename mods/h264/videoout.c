/*
 * n3videoout - stream the goggles' encoded app-liveview H.264 to a PC.
 *
 * Opens OMX.dji.video_reader.avc.mdc on zv900_app_liveview_chn, prepends the
 * vc8000e sequence header (real SPS/PPS measured from the vendor encoder), and
 * serves Annex-B H.264 on TCP 5571 to one client at a time.
 *
 * Armed by /data/local/tmp/videoout_on; stops when that file is removed.
 * Read-only consumer: it never starts/stops the media pipeline.
 */
#define NTLOG_PREFIX "vout"
#include "natartos_common.h"

#include <OMX_Types.h>
#include <OMX_Core.h>
#include <OMX_Component.h>
#include <OMX_Video.h>
#include <OMX_Index.h>

typedef void *(*dlsym_fn)(void *handle, const char *name);
typedef void *(*dlopen_fn)(const char *path, int mode);
typedef int (*pthread_create_fn)(unsigned long *, const void *,
                                 void *(*)(void *), void *);

#define RTLD_NOW 2

#define ARM_PATH   "/data/local/tmp/videoout_on"
#define STAT_PATH  "/data/local/tmp/videoout.stat"
#define PORT       5571
#define RING_SIZE  (4 * 1024 * 1024)
#define CHUNK      65536

#define CHAN_JSON "{\"channel_id\":1,\"device\":\"local_mdc\"," \
                  "\"name\":\"zv900_app_liveview_chn\",\"type\":0}"

/* Real vc8000e sequence header for the liveview pipe (High, level 5.2). */
static const unsigned char SPS_PPS[] = {
    0x00, 0x00, 0x00, 0x01, 0x67, 0x64, 0x00, 0x34, 0xac, 0x4d, 0x00, 0xf0,
    0x04, 0x4f, 0xcb, 0x35, 0x01, 0x01, 0x01, 0x40, 0x00, 0x00, 0x03, 0x00,
    0x40, 0x00, 0x00, 0x1e, 0x03, 0xc7, 0x0c, 0xa8,
    0x00, 0x00, 0x00, 0x01, 0x68, 0xee, 0x3c, 0xb0,
};

/* ---- extra syscalls (AArch64) ---- */
#define __NR_socket      198
#define __NR_bind        200
#define __NR_listen      201
#define __NR_accept      202
#define __NR_sendto      206
#define __NR_recvfrom    207
#define __NR_setsockopt  208
#define __NR_close       57
#define __NR_fcntl       25
#define __NR_unlinkat    35

struct sockaddr_in_t {
    unsigned short sin_family;
    unsigned short sin_port;
    unsigned int sin_addr;
    unsigned char pad[8];
};

struct timeval_t { long tv_sec; long tv_usec; };

static inline long sys_socket(int d, int t, int p) {
    register long x0 __asm__("x0") = d;
    register long x1 __asm__("x1") = t;
    register long x2 __asm__("x2") = p;
    register long x8 __asm__("x8") = __NR_socket;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline long sys_bind(int fd, void *a, int l) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)a;
    register long x2 __asm__("x2") = l;
    register long x8 __asm__("x8") = __NR_bind;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline long sys_listen(int fd, int n) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = n;
    register long x8 __asm__("x8") = __NR_listen;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return x0;
}

static inline long sys_accept(int fd, void *a, void *l) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)a;
    register long x2 __asm__("x2") = (long)l;
    register long x8 __asm__("x8") = __NR_accept;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline long sys_send(int fd, const void *b, long n, int flags) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)b;
    register long x2 __asm__("x2") = n;
    register long x3 __asm__("x3") = flags;
    register long x4 __asm__("x4") = 0;   /* dest_addr */
    register long x5 __asm__("x5") = 0;   /* addrlen */
    register long x8 __asm__("x8") = __NR_sendto;
    __asm__ volatile("svc 0" : "+r"(x0), "+r"(x4), "+r"(x5)
                     : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
    return x0;
}

static inline long sys_setsockopt(int fd, int lvl, int name, void *v, int l) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = lvl;
    register long x2 __asm__("x2") = name;
    register long x3 __asm__("x3") = (long)v;
    register long x4 __asm__("x4") = l;
    register long x8 __asm__("x8") = __NR_setsockopt;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory");
    return x0;
}

static inline long sys_fcntl(int fd, int cmd, long arg) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = cmd;
    register long x2 __asm__("x2") = arg;
    register long x8 __asm__("x8") = __NR_fcntl;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline long sys_unlink(const char *p) {
    register long x0 __asm__("x0") = AT_FDCWD;
    register long x1 __asm__("x1") = (long)p;
    register long x2 __asm__("x2") = 0;
    register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static long sys_nanosleep_(long ms) {
    struct timespec_t ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    return sys_nanosleep(&ts, 0);
}

static void mem_copy(void *dst, const void *src, long n) {
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    for (long i = 0; i < n; i++) d[i] = s[i];
}

static int marker_present(void) {
    return sys_faccessat(AT_FDCWD, ARM_PATH, 0) == 0;
}

/* ---- state ---- */
static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_comp;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_state_ok;
static volatile int g_err;
static volatile int g_running;      /* streaming session live */
static volatile int g_sender_run;
static volatile int g_client_fd = -1;
static volatile long g_frames, g_bytes, g_dropped, g_sent;
static volatile int g_lock;

static unsigned char g_ring[RING_SIZE];
static volatile long g_head, g_tail;   /* absolute byte counters */

static void lock(void) {
    while (__sync_lock_test_and_set(&g_lock, 1)) __asm__ volatile("yield");
}
static void unlock(void) { __sync_lock_release(&g_lock); }

static void put_stat(int client) {
    char buf[160];
    int n = 0;
    const char *k[] = { "client=", "frames=", "bytes=", "dropped=", "sent=" };
    long v[5];
    v[0] = client; v[1] = g_frames; v[2] = g_bytes; v[3] = g_dropped; v[4] = g_sent;
    for (int i = 0; i < 5; i++) {
        for (const char *p = k[i]; *p; p++) buf[n++] = *p;
        char tmp[20];
        int t = 0;
        long x = v[i] < 0 ? 0 : v[i];
        if (!x) tmp[t++] = '0';
        while (x > 0) { tmp[t++] = (char)('0' + (x % 10)); x /= 10; }
        while (t > 0) buf[n++] = tmp[--t];
        buf[n++] = ' ';
    }
    buf[n++] = '\n';
    int fd = (int)sys_openat(AT_FDCWD, STAT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) { sys_write_raw(fd, buf, n); sys_close(fd); }
}

/* ---- OMX helpers ---- */
static void set_ver(OMX_PARAM_PORTDEFINITIONTYPE *pd) {
    pd->nSize = sizeof(*pd);
    pd->nVersion.s.nVersionMajor = 1;
    pd->nVersion.s.nVersionMinor = 0;
    pd->nVersion.s.nRevision = 0;
    pd->nVersion.s.nStep = 0;
}

static OMX_ERRORTYPE on_event(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                              OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) g_state_ok = 1;
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event error=", (int)d1); }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_empty(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b;
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_fill(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    if (b->nFilledLen) {
        long len = (long)b->nFilledLen;
        g_frames++;
        g_bytes += len;
        if (g_client_fd >= 0) {
            lock();
            long used = g_head - g_tail;
            if (used + len <= RING_SIZE) {
                long pos = g_head % RING_SIZE;
                long first = RING_SIZE - pos;
                if (first > len) first = len;
                mem_copy(g_ring + pos, b->pBuffer + b->nOffset, first);
                if (len > first)
                    mem_copy(g_ring, b->pBuffer + b->nOffset + first, len - first);
                g_head += len;
            } else {
                g_dropped++;
            }
            unlock();
        }
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };
static OMX_BUFFERHEADERTYPE *g_bufs[6];
static int g_nbufs;

static int send_all(int fd, const unsigned char *p, long n) {
    long off = 0;
    while (off < n) {
        long w = sys_send(fd, p + off, n - off, 0x4000 /* MSG_NOSIGNAL */);
        if (w <= 0) return 0;
        off += w;
        g_sent += w;
    }
    return 1;
}

static void *sender_worker(void *arg) {
    (void)arg;
    static unsigned char chunk[CHUNK];
    long last_stat = 0;
    while (g_sender_run) {
        int fd = g_client_fd;
        if (fd < 0) { sys_nanosleep_(10); continue; }
        long n = 0;
        lock();
        long used = g_head - g_tail;
        if (used > CHUNK) used = CHUNK;
        if (used > 0) {
            long pos = g_tail % RING_SIZE;
            long first = RING_SIZE - pos;
            if (first > used) first = used;
            mem_copy(chunk, g_ring + pos, first);
            if (used > first) mem_copy(chunk + first, g_ring, used - first);
            g_tail += used;
            n = used;
        }
        unlock();
        if (!n) { sys_nanosleep_(2); continue; }
        if (!send_all(fd, chunk, n)) {
            NTLOG("client send failed, closing");
            sys_close(fd);
            g_client_fd = -1;
        }
        long now = g_frames / 60;
        if (now != last_stat) { last_stat = now; put_stat(g_client_fd >= 0); }
    }
    return 0;
}

static void reset_ring(void) {
    lock();
    g_head = 0;
    g_tail = 0;
    unlock();
}

/* ---- one streaming session: component stays open while armed ---- */
static pthread_create_fn g_pcreate;

static int omx_start(void) {
    dlopen_fn pdlopen = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pdlsym = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    if (!pdlopen || !pdlsym) { NTLOG("no dlopen"); return 0; }

    void *core = pdlopen("libOmxCore.so", RTLD_NOW);
    if (!core) { NTLOG("no core"); return 0; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))pdlsym(core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        pdlsym(core, "OMX_GetHandle");
    if (!init || !get) { NTLOG("no core entry"); return 0; }
    g_free_handle = (OMX_ERRORTYPE (*)(OMX_HANDLETYPE))
        pdlsym(core, "OMX_FreeHandle");
    init();

    OMX_ERRORTYPE e = get(&g_comp, "OMX.dji.video_reader.avc.mdc", 0, &g_cbs);
    NTLOG_INT("handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) return 0;

    static unsigned char uri_buf[512];
    for (unsigned i = 0; i < sizeof(uri_buf); i++) uri_buf[i] = 0;
    OMX_PARAM_CONTENTURITYPE *uri = (OMX_PARAM_CONTENTURITYPE *)uri_buf;
    const char *json = CHAN_JSON;
    int jl = 0; while (json[jl]) jl++;
    uri->nSize = sizeof(OMX_PARAM_CONTENTURITYPE) + jl;
    uri->nVersion.s.nVersionMajor = 1;
    uri->nVersion.s.nVersionMinor = 0;
    uri->nVersion.s.nRevision = 0;
    uri->nVersion.s.nStep = 0;
    for (int i = 0; i <= jl; i++) uri->contentURI[i] = (OMX_U8)json[i];
    NTLOG_INT("uri=", (int)OMX_SetParameter(g_comp, OMX_IndexParamContentURI, uri));

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    OMX_U32 out_port = 0;
    int found = 0;
    for (OMX_U32 i = 0; i < 3; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd);
        pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        if (pd.eDir == OMX_DirOutput) { out_port = i; found = 1; break; }
    }
    if (!found) { NTLOG("no output port"); return 0; }

    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd);
    pd.nPortIndex = out_port;
    OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);

    int n = 0;
    int want = (int)pd.nBufferCountActual;
    if (want > 6) want = 6;
    for (int i = 0; i < want; i++) {
        OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &g_bufs[i], out_port, 0,
                                             pd.nBufferSize);
        if (a != OMX_ErrorNone) { NTLOG_INT("alloc err=", (int)a); break; }
        n++;
    }
    g_nbufs = n;
    if (!n) { NTLOG("no buffers"); return 0; }
    NTLOG_INT("bufs=", n);

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) sys_nanosleep_(10);
    if (!g_state_ok) { NTLOG_INT("idle failed=", g_err); return 0; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) sys_nanosleep_(10);
    if (!g_state_ok) { NTLOG_INT("exec failed=", g_err); return 0; }

    for (int i = 0; i < n; i++) OMX_FillThisBuffer(g_comp, g_bufs[i]);
    NTLOG("capturing");
    return 1;
}

static void omx_stop(void) {
    if (!g_comp) return;
    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 100 && !g_state_ok && !g_err; i++) sys_nanosleep_(10);
    for (int i = 0; i < g_nbufs; i++) {
        if (g_bufs[i]) OMX_FreeBuffer(g_comp, 0, g_bufs[i]);
        g_bufs[i] = 0;
    }
    g_nbufs = 0;
    if (g_free_handle) g_free_handle(g_comp);
    else NTLOG("no OMX_FreeHandle, handle left idle");
    g_comp = 0;
    NTLOG("component closed");
}

static void *mod_worker(void *arg) {
    (void)arg;
    int listen_fd = -1;
    int sender_tid = 0;
    int sender_started = 0;

    for (;;) {
        int armed = marker_present();

        if (!armed) {
            if (g_running) {
                NTLOG("disarmed, stopping");
                g_sender_run = 0;
                if (sender_started) { sys_nanosleep_(50); sender_started = 0; }
                if (g_client_fd >= 0) { sys_close(g_client_fd); g_client_fd = -1; }
                omx_stop();
                if (listen_fd >= 0) { sys_close(listen_fd); listen_fd = -1; }
                put_stat(0);
                g_running = 0;
            }
            sys_nanosleep_(200);
            continue;
        }

        if (!g_running) {
            NTLOG("armed, starting");
            reset_ring();
            g_frames = g_bytes = g_dropped = g_sent = 0;
            if (!omx_start()) {
                NTLOG("omx start failed");
                sys_unlink(ARM_PATH);
                sys_nanosleep_(500);
                continue;
            }
            g_sender_run = 1;
            if (!g_pcreate((unsigned long *)&sender_tid, 0,
                           (void *(*)(void *))sender_worker, 0)) {
                sender_started = 1;
            } else {
                NTLOG("sender thread failed");
                g_sender_run = 0;
                omx_stop();
                sys_unlink(ARM_PATH);
                sys_nanosleep_(500);
                continue;
            }

            listen_fd = (int)sys_socket(2 /*AF_INET*/, 1 /*SOCK_STREAM*/, 0);
            if (listen_fd < 0) { NTLOG("socket failed"); }
            else {
                int one = 1;
                sys_setsockopt(listen_fd, 1, 2 /*SO_REUSEADDR*/, &one, 4);
                struct sockaddr_in_t sa;
                for (unsigned i = 0; i < sizeof(sa); i++) ((unsigned char *)&sa)[i] = 0;
                sa.sin_family = 2;
                sa.sin_port = (unsigned short)((PORT >> 8) | ((PORT & 0xff) << 8));
                sa.sin_addr = 0;
                if (sys_bind(listen_fd, &sa, sizeof(sa)) != 0) {
                    NTLOG("bind failed");
                    sys_close(listen_fd);
                    listen_fd = -1;
                } else {
                    sys_listen(listen_fd, 2);
                    sys_fcntl(listen_fd, 4 /*F_SETFL*/, 0x800 /*O_NONBLOCK*/);
                    NTLOG("listening on 5571");
                }
            }
            g_running = 1;
        }

        if (listen_fd >= 0 && g_client_fd < 0) {
            int fd = (int)sys_accept(listen_fd, 0, 0);
            if (fd >= 0) {
                struct timeval_t tv;
                tv.tv_sec = 1; tv.tv_usec = 0;
                sys_setsockopt(fd, 1, 20 /*SO_SNDTIMEO*/, &tv, sizeof(tv));
                lock();
                g_head = 0;
                g_tail = 0;
                /* queue the sequence header first */
                long pos = g_head % RING_SIZE;
                long len = (long)sizeof(SPS_PPS);
                long first = RING_SIZE - pos;
                if (first > len) first = len;
                mem_copy(g_ring + pos, SPS_PPS, first);
                if (len > first) mem_copy(g_ring, SPS_PPS + first, len - first);
                g_head += len;
                unlock();
                g_client_fd = fd;
                NTLOG("client connected");
            }
        }

        long now_ms = g_frames;   /* cheap monotonic-ish tick */
        static long last_stat_tick;
        if (now_ms / 60 != last_stat_tick / 60) {
            last_stat_tick = now_ms;
            put_stat(g_client_fd >= 0);
        }
        sys_nanosleep_(100);
    }
    (void)sender_tid;
    return 0;
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    if (!g_dlsym) return 1;
    g_pcreate = (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!g_pcreate) { NTLOG("no pthread"); return 1; }
    unsigned long tid;
    g_pcreate(&tid, 0, (void *(*)(void *))mod_worker, 0);
    return 0;
}
