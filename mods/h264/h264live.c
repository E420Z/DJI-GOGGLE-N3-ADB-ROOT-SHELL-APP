/*
 * n3h264live - live H.264 receiver + vendor decoder + display sink.
 *
 * Listens on TCP 5572 for [u32le len][Annex-B access unit] frames, feeds each
 * AU to OMX.dji.video_decoder.avc.ffmpeg with ENDOFFRAME, and forwards the
 * decoded NV12 straight into OMX.dji.iv_renderer.yuv.extra_blending (the Air
 * Unit liveview plane). No BGRA conversion, no fb_shared, no 12 fps hook cap.
 *
 * Two optional trigger files:
 *   /data/local/tmp/h264live_sink  -> use extra_blending instead of fb_shared
 *   /data/local/tmp/h264live_fork  -> fork child, close inherited fds, kill the
 *                                     UI parent so its gfx0 plane releases.
 * Without them the old fb_shared + hook_overlay path still works.
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
#define FORK_PATH "/data/local/tmp/h264live_fork"
#define SINK_PATH "/data/local/tmp/h264live_sink"
#define HW_PATH "/data/local/tmp/h264live_hw"
#define HEVC_PATH "/data/local/tmp/h264live_hevc"
#define DEC_PATH "/data/local/tmp/h264live_decode"
#define P720_PATH "/data/local/tmp/h264live_720"
#define TUNNEL_PATH "/data/local/tmp/h264live_tunnel"
#define STAT_PATH "/data/local/tmp/h264live.stat"
#define PORT 5572
#define MAX_AU (1024 * 1024)
#define FB_W 1920
#define FB_H 1080
#define SU_W 640
#define SU_H 360
#define NBUF 7
#define MAXP 2
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
static OMX_ERRORTYPE (*g_setup_tunnel)(OMX_HANDLETYPE, OMX_U32,
                                       OMX_HANDLETYPE, OMX_U32);
static int g_tunnel;
static volatile int g_state_ok, g_err, g_eos;
static volatile int g_fill_calls, g_empty_calls, g_frames, g_tun_frames;static volatile long g_bytes;
static int g_fd = -1;
static int g_display;
static void publish_nv12(const unsigned char *yuv);
static void display_stop(void);
static int display_init(void);
static OMX_BUFFERHEADERTYPE *g_ib[16], *g_ob[16];
static int g_ni, g_no;
static OMX_U32 g_in_port, g_out_port;
static long g_ts;
static long g_in_alloc;

/* ---- display sink: extra_blending ------------------------------------- */
static OMX_ERRORTYPE (*g_omx_get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR,
                                  OMX_CALLBACKTYPE *);
static OMX_HANDLETYPE g_sink;
static volatile int g_sink_state_ok, g_sink_err;
static OMX_U32 g_sink_ports[MAXP];
static int g_sink_np;
static OMX_BUFFERHEADERTYPE *g_sink_buf[MAXP][NBUF];
static volatile int g_sink_ready[MAXP][NBUF];
static int g_sink_bn[MAXP];
static int g_sink_next[MAXP];
static int g_sink_stride[MAXP], g_sink_slice[MAXP];
static volatile int g_sink_on, g_sink_sent, g_sink_empty_calls, g_sink_drop;
static long g_sink_ts;

/* Decoder fill callback -> free sink buffer directly; a tiny thread only
 * issues EmptyThisBuffer. This removes one full-frame copy and the queue
 * delay that made the stream feel laggy. */
static volatile int g_pending[MAXP][NBUF];
static int g_pq[NBUF];
static volatile int g_pq_head, g_pq_tail, g_pq_count;
static volatile int g_q_stop;
static pthread_create_fn g_pcreate;
static int g_dec_stride = FB_W, g_dec_slice = FB_H;
static int g_dec_w = FB_W, g_dec_h = FB_H;
static int g_uv_swap;
static int g_planar = 1;   /* software ffmpeg decoder emits I420 planar */
static int g_hevc;
static int g_cfg_done;
static int g_decode_only;
static int g_dump_done;

static int n3_contains(const char *s, const char *sub) {
    for (; *s; s++) {
        const char *a = s, *b = sub;
        while (*a && *b && *a == *b) { a++; b++; }
        if (!*b) return 1;
    }
    return 0;
}

static int sink_init(void);
static void sink_close(void);
static int sink_fill_main(const unsigned char *yuv);
static void sink_push_sub(void);
static void sink_copy_main(OMX_BUFFERHEADERTYPE *b, const unsigned char *yuv);
static void *sink_thread(void *arg);
static void sink_maybe_nolut(void);

static void set_ver(OMX_PARAM_PORTDEFINITIONTYPE *pd) {
    pd->nSize = sizeof(*pd);
    pd->nVersion.s.nVersionMajor = 1;
    pd->nVersion.s.nVersionMinor = 0;
    pd->nVersion.s.nRevision = 0;
    pd->nVersion.s.nStep = 0;
}

/* Standard OMX colour-space param, absent from this SDK header. */
typedef struct {
    OMX_U32 nSize;
    OMX_VERSIONTYPE nVersion;
    OMX_U32 nPortIndex;
    OMX_U32 eColorSpace;
} n3_color_space_t;

static int set_colorspace(OMX_HANDLETYPE comp, OMX_U32 port, OMX_U32 cs) {
    n3_color_space_t c;
    for (unsigned i = 0; i < sizeof(c); i++) ((unsigned char *)&c)[i] = 0;
    c.nSize = sizeof(c);
    c.nVersion.s.nVersionMajor = 1;
    c.nPortIndex = port;
    c.eColorSpace = cs;
    return (int)OMX_SetParameter(comp, OMX_IndexParamColorSpace, &c);
}

static int put_num(char *b, int n, const char *k, long x) {
    while (*k) b[n++] = *k++;
    char t[16]; int m = 0;
    if (!x) t[m++] = '0';
    while (x) { t[m++] = (char)('0' + x % 10); x /= 10; }
    while (m) b[n++] = t[--m];
    b[n++] = '\n';
    return n;
}

static void put_stat(void) {
    char b[128]; int n = 0;
    n = put_num(b, n, "frames=", g_frames);
    n = put_num(b, n, "sink=", g_sink_sent);
    n = put_num(b, n, "sinkempty=", g_sink_empty_calls);
    n = put_num(b, n, "inempty=", g_empty_calls);
    n = put_num(b, n, "drop=", g_sink_drop);
    n = put_num(b, n, "qdrop=", 0);
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
        long denom = (long)g_dec_h * 3 / 2;
        if ((long)b->nFilledLen >= denom && ((long)b->nFilledLen % denom) == 0) {
            int s = (int)((long)b->nFilledLen / denom);
            if (s >= g_dec_w && s <= 2048) g_dec_stride = s;
        }
        if (g_decode_only) {
            /* diagnostic: decode only, no sink/display */
        } else if (g_tunnel) {
            /* output port is tunneled straight into the sink */
        } else if (g_sink_on) {
            sink_fill_main(b->pBuffer + b->nOffset);
        } else if (g_display) {
            publish_nv12(b->pBuffer + b->nOffset);
        }
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

/* ---- display sink: OMX.dji.iv_renderer.yuv.extra_blending ------------- */

static void fast_copy(unsigned char *d, const unsigned char *s, long n) {
    while (n >= 8) {
        *(unsigned long long *)d = *(const unsigned long long *)s;
        d += 8; s += 8; n -= 8;
    }
    while (n-- > 0) *d++ = *s++;
}

static void fast_fill(unsigned char *d, unsigned char v, long n) {
    unsigned long long p = 0x0101010101010101ULL * v;
    while (n >= 8) { *(unsigned long long *)d = p; d += 8; n -= 8; }
    while (n-- > 0) *d++ = v;
}

/* The Air Unit pipeline passes this URL via OMX_SetParameter(0x0100000D).
 * Struct from PipeBuilder::setNodeUrl: nSize = len + 0xd, version 1, URL at +8. */
static void sink_set_url(void) {
    static const char url[] =
        "{\"config_file\":\"/etc/display_frame_rate_map.json\","
        "\"enable_aux_liveview\":false,"
        "\"sub_stream_h_offset\":144,\"sub_stream_v_offset\":64,"
        "\"sub_stream_width\":496,\"sub_stream_height\":280,"
        "\"notify_sub_stream_alive_status\":true}";
    unsigned char buf[0x200];
    for (unsigned i = 0; i < sizeof(buf); i++) buf[i] = 0;
    int n = (int)sizeof(url) - 1;
    *(unsigned int *)buf = (unsigned int)(n + 0xd);
    *(unsigned int *)(buf + 4) = 1;
    for (int i = 0; i <= n; i++) buf[8 + i] = (unsigned char)url[i];
    OMX_ERRORTYPE e = OMX_SetParameter(g_sink, (OMX_INDEXTYPE)0x0100000D, buf);
    NTLOG_INT("url ret=", (int)e);
}

static OMX_ERRORTYPE sink_ev(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                             OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) g_sink_state_ok = 1;
    if (e == OMX_EventError) { g_sink_err = (int)d1; NTLOG_INT("sink err=", (int)d1); }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE sink_emp(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a;
    for (int p = 0; p < g_sink_np; p++) {
        for (int i = 0; i < g_sink_bn[p]; i++) {
            if (b == g_sink_buf[p][i]) {
                g_sink_ready[p][i] = 1;
                g_sink_empty_calls++;
                return OMX_ErrorNone;
            }
        }
    }
    g_sink_empty_calls++;
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE sink_fil(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b; return OMX_ErrorNone;
}
static OMX_CALLBACKTYPE g_sink_cbs = { sink_ev, sink_emp, sink_fil };

static int sink_pick(int p) {
    int n = g_sink_bn[p];
    for (int k = 0; k < n; k++) {
        int i = (g_sink_next[p] + k) % n;
        if (g_sink_ready[p][i]) {
            g_sink_ready[p][i] = 0;
            g_sink_next[p] = (i + 1) % n;
            return i;
        }
    }
    return -1;
}

static int sink_init(void) {
    if (!g_omx_get) return -1;
    int ufd = (int)sys_openat(AT_FDCWD, "/data/local/tmp/h264live_uv", 0, 0);
    if (ufd >= 0) {
        char c = 0;
        if (sys_read(ufd, &c, 1) == 1 && c == '1') g_uv_swap = 1;
        sys_close(ufd);
    }
    NTLOG_INT("uv swap=", g_uv_swap);
    const char *names[2] = { "OMX.dji.iv_renderer.yuv.extra_blending",
                             "OMX.dji.iv_renderer.yuv.liveview" };
    OMX_ERRORTYPE e = OMX_ErrorUndefined;
    for (int i = 0; i < 2 && !g_sink; i++) {
        e = g_omx_get(&g_sink, (OMX_STRING)names[i], 0, &g_sink_cbs);
        NTLOG_INT(i == 0 ? "extra_blending=" : "liveview=", (int)e);
        if (e != OMX_ErrorNone) g_sink = 0;
    }
    if (!g_sink) return -1;
    sink_set_url();
    NTLOG("sink url done");

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    g_sink_np = 0;
    for (OMX_U32 i = 0; i < 4; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = i;
        if (OMX_GetParameter(g_sink, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        if (pd.eDir == OMX_DirInput && g_sink_np < MAXP) g_sink_ports[g_sink_np++] = i;
    }
    NTLOG_INT("sink ports=", g_sink_np);
    if (g_sink_np < 2) { sink_close(); return -1; }

    for (int p = 0; p < MAXP; p++) {
        OMX_U32 port = g_sink_ports[p];
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_sink, OMX_IndexParamPortDefinition, &pd);
        int pw = (p == 0) ? FB_W : SU_W;
        int ph = (p == 0) ? FB_H : SU_H;
        pd.format.video.nFrameWidth = pw;
        pd.format.video.nFrameHeight = ph;
        pd.format.video.nStride = pw;
        pd.format.video.nSliceHeight = ph;
        pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
        pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
        pd.format.video.xFramerate = 60 << 16;
        pd.nBufferCountActual = NBUF;
        NTLOG_INT(p == 0 ? "sink main set=" : "sink sub set=",
                  (int)OMX_SetParameter(g_sink, OMX_IndexParamPortDefinition, &pd));

        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_sink, OMX_IndexParamPortDefinition, &pd);
        g_sink_stride[p] = (int)pd.format.video.nStride;
        g_sink_slice[p] = (int)pd.format.video.nSliceHeight;
        if (!g_sink_stride[p]) g_sink_stride[p] = pw;
        if (!g_sink_slice[p]) g_sink_slice[p] = ph;
        NTLOG_INT(p == 0 ? "sink main size=" : "sink sub size=", (int)pd.nBufferSize);
        NTLOG_INT("  stride=", g_sink_stride[p]);
        NTLOG_INT("  slice=", g_sink_slice[p]);
        for (int i = 0; i < NBUF; i++) {
            if (g_tunnel && p == 0) break;   /* main port is tunneled */
            OMX_BUFFERHEADERTYPE *b = 0;
            OMX_ERRORTYPE a = OMX_AllocateBuffer(g_sink, &b, port, 0, pd.nBufferSize);
            if (a != OMX_ErrorNone) { NTLOG_INT("  alloc err=", (int)a); break; }
            g_sink_buf[p][g_sink_bn[p]] = b;
            g_sink_ready[p][g_sink_bn[p]] = 1;
            g_sink_bn[p]++;
        }
        NTLOG_INT("  bufs=", g_sink_bn[p]);
        if (!g_sink_bn[p] && !(g_tunnel && p == 0)) { sink_close(); return -1; }
    }

    NTLOG_INT("sink cs=", set_colorspace(g_sink, g_sink_ports[0], 2 /*BT601*/));

    if (g_tunnel) {
        g_sink_on = 1;
        return 0;
    }

    g_sink_state_ok = 0; g_sink_err = 0;
    OMX_SendCommand(g_sink, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_sink_state_ok && !g_sink_err; i++) {
        struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
    }
    NTLOG_INT("sink idle=", g_sink_state_ok);
    if (!g_sink_state_ok) { sink_close(); return -1; }

    g_sink_state_ok = 0; g_sink_err = 0;
    OMX_SendCommand(g_sink, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_sink_state_ok && !g_sink_err; i++) {
        struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
    }
    NTLOG_INT("sink exec=", g_sink_state_ok);
    if (!g_sink_state_ok) { sink_close(); return -1; }

    g_sink_on = 1;
    return 0;
}

static void sink_close(void) {
    g_sink_on = 0;
    if (!g_sink) return;
    g_sink_state_ok = 0;
    OMX_SendCommand(g_sink, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 100 && !g_sink_state_ok; i++) {
        struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
    }
    for (int p = 0; p < g_sink_np; p++) {
        for (int i = 0; i < g_sink_bn[p]; i++) {
            if (g_sink_buf[p][i]) OMX_FreeBuffer(g_sink, g_sink_ports[p], g_sink_buf[p][i]);
        }
    }
    if (g_free_handle) g_free_handle(g_sink);
    g_sink = 0;
    NTLOG("sink closed");
}

static void sink_copy_main(OMX_BUFFERHEADERTYPE *b, const unsigned char *yuv) {
    int st = g_sink_stride[0], sl = g_sink_slice[0];
    if (st < FB_W || sl < FB_H) return;
    unsigned char *d = b->pBuffer;
    if (!g_planar && g_dec_stride == st && g_dec_slice == sl) {
        /* hardware decoder already matches the sink: one straight copy */
        fast_copy(d, yuv, (long)st * sl * 3 / 2);
    } else {
    for (int r = 0; r < FB_H; r++)
        fast_copy(d + (long)r * st, yuv + (long)r * g_dec_stride, FB_W);

    /* The vendor decoder outputs I420 planar: Y, then U, then V. The sink
     * wants NV12 semi-planar, so interleave U/V with 32-bit stores. */
    const unsigned char *u = yuv + (long)g_dec_stride * g_dec_slice;
    const unsigned char *v = u + (long)(g_dec_stride / 2) * (g_dec_slice / 2);
    unsigned char *duv = d + (long)st * sl;
    int cw = FB_W / 2;
    if (g_planar) {
        for (int r = 0; r < FB_H / 2; r++) {
            unsigned char *row = duv + (long)r * st;
            const unsigned char *ur = u + (long)r * (g_dec_stride / 2);
            const unsigned char *vr = v + (long)r * (g_dec_stride / 2);
            int x = 0;
            for (; x + 1 < cw; x += 2) {
                unsigned short u2, v2;
                __builtin_memcpy(&u2, ur + x, 2);
                __builtin_memcpy(&v2, vr + x, 2);
                unsigned int w;
                if (g_uv_swap)
                    w = (unsigned int)(v2 & 0xFF) |
                        ((unsigned int)(u2 & 0xFF) << 8) |
                        ((unsigned int)((v2 >> 8) & 0xFF) << 16) |
                        ((unsigned int)((u2 >> 8) & 0xFF) << 24);
                else
                    w = (unsigned int)(u2 & 0xFF) |
                        ((unsigned int)(v2 & 0xFF) << 8) |
                        ((unsigned int)((u2 >> 8) & 0xFF) << 16) |
                        ((unsigned int)((v2 >> 8) & 0xFF) << 24);
                __builtin_memcpy(row + 2 * x, &w, 4);
            }
            if (x < cw) {
                row[2 * x] = g_uv_swap ? vr[x] : ur[x];
                row[2 * x + 1] = g_uv_swap ? ur[x] : vr[x];
            }
        }
    } else {
        /* hardware decoder: NV12, U/V already interleaved */
        for (int r = 0; r < FB_H / 2; r++) {
            unsigned char *row = duv + (long)r * st;
            const unsigned char *s = u + (long)r * g_dec_stride;
            if (g_uv_swap) {
                for (int x = 0; x + 1 < FB_W; x += 2) {
                    row[x] = s[x + 1];
                    row[x + 1] = s[x];
                }
            } else {
                fast_copy(row, s, FB_W);
            }
        }
    }
    }

    b->nFilledLen = (OMX_U32)((long)st * sl * 3 / 2);
    b->nOffset = 0;
    b->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
    b->nTimeStamp = g_sink_ts;
    g_sink_ts += 16666;
    if (!g_dump_done) {
        g_dump_done = 1;
        int fd = (int)sys_openat(AT_FDCWD, "/data/local/tmp/sink_dump.raw",
                                 O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) {
            sys_write_raw(fd, b->pBuffer, (long)st * sl * 3 / 2);
            sys_close(fd);
        }
    }
}

static int sink_fill_main(const unsigned char *yuv) {
    if (!g_sink_on || !g_sink || g_sink_bn[0] <= 0) return -1;
    int i = sink_pick(0);
    if (i < 0) { g_sink_drop++; return -1; }
    sink_copy_main(g_sink_buf[0][i], yuv);
    g_pending[0][i] = 1;
    if (g_pq_count < NBUF) {
        g_pq[g_pq_head] = i;
        g_pq_head = (g_pq_head + 1) % NBUF;
        __atomic_add_fetch(&g_pq_count, 1, __ATOMIC_RELEASE);
    } else {
        g_pending[0][i] = 0;
        g_sink_ready[0][i] = 1;
        g_sink_drop++;
    }
    return 0;
}

static void *sink_thread(void *arg) {
    (void)arg;
    while (!g_q_stop) {
        if (__atomic_load_n(&g_pq_count, __ATOMIC_ACQUIRE) == 0) {
            struct timespec_t t = { 0, 500000 }; sys_nanosleep(&t, 0);
            continue;
        }
        int i = g_pq[g_pq_tail];
        g_pq_tail = (g_pq_tail + 1) % NBUF;
        __atomic_sub_fetch(&g_pq_count, 1, __ATOMIC_RELEASE);
        if (!g_sink_on) continue;
        if (g_pending[0][i]) {
            g_pending[0][i] = 0;
            OMX_EmptyThisBuffer(g_sink, g_sink_buf[0][i]);
            g_sink_sent++;
        }
        sink_push_sub();
    }
    return 0;
}

static void sink_maybe_nolut(void) {
    if (!g_sink) return;
    if (sys_faccessat(AT_FDCWD, "/data/local/tmp/h264live_nolut", 0) != 0) return;
    dlopen_fn pdl = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pds = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    if (!pdl || !pds) { NTLOG("nolut: no dl"); return; }
    void *lib = pdl("libOmxLiveDispSink.so", RTLD_NOW);
    if (!lib) lib = pdl("/system/lib64/libOmxLiveDispSink.so", RTLD_NOW);
    if (!lib) { NTLOG("nolut: no lib"); return; }
    typedef void (*lut_fn)(void *, int, char *);
    lut_fn f = (lut_fn)pds(lib, "_ZN3dji11DisplaySink8set3DLUTE8OMX_BOOLPc");
    void *obj = *(void **)((char *)g_sink + 8);
    NTLOG_HEX("lut fn=", (unsigned long)f);
    NTLOG_HEX("lut obj=", (unsigned long)obj);
    if (!f || !obj) { NTLOG("nolut: no fn/obj"); return; }
    f(obj, 0, (char *)"");
    NTLOG("3dlut disabled");
}

static void sink_set_csc(int cs) {
    if (!g_sink) return;
    dlopen_fn pdl = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pds = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    if (!pdl || !pds) { NTLOG("csc: no dl"); return; }
    void *lib = pdl("libOmxLiveDispSink.so", RTLD_NOW);
    if (!lib) lib = pdl("/system/lib64/libOmxLiveDispSink.so", RTLD_NOW);
    if (!lib) { NTLOG("csc: no lib"); return; }
    typedef int (*csc_fn)(void *, void *, int, unsigned long, unsigned long);
    csc_fn f = (csc_fn)pds(
        lib, "_ZN3dji11DisplaySink25setColorSpaceConvertParamEP25duss_"
             "disp_instance_info_ta30OMX_CONFIG_VIDEOCOLORSPACETYPE");
    void *obj = *(void **)((char *)g_sink + 8);
    void *disp = obj ? *(void **)((char *)obj + 0x250) : 0;
    NTLOG_HEX("csc fn=", (unsigned long)f);
    NTLOG_HEX("csc obj=", (unsigned long)obj);
    NTLOG_HEX("csc disp=", (unsigned long)disp);
    if (!f || !obj || !disp) { NTLOG("csc: no fn/obj/disp"); return; }
    int r = f(obj, disp, cs, 0, 0);
    NTLOG_INT("csc ret=", r);
}

static void sink_push_sub(void) {
    if (!g_sink_on || !g_sink || g_sink_bn[1] <= 0) return;
    int i = sink_pick(1);
    if (i < 0) return;
    OMX_BUFFERHEADERTYPE *b = g_sink_buf[1][i];
    int st = g_sink_stride[1], sl = g_sink_slice[1];
    long ysz = (long)st * sl;
    fast_fill(b->pBuffer, 16, ysz);
    fast_fill(b->pBuffer + ysz, 128, ysz / 2);
    b->nFilledLen = (OMX_U32)(ysz * 3 / 2);
    b->nOffset = 0;
    b->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
    b->nTimeStamp = g_sink_ts;
    OMX_EmptyThisBuffer(g_sink, b);
}

static void teardown(void) {
    g_q_stop = 1;
    g_sink_on = 0;
    { struct timespec_t t = { 0, 50000000 }; sys_nanosleep(&t, 0); }
    if (g_tunnel && g_comp) {
        g_state_ok = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_state_ok; i++) {
            struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
        }
    }
    if (g_sink) sink_close();
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

/* Extract SPS/PPS (AVC) or VPS/SPS/PPS (HEVC) from an Annex-B AU. The
 * hardware vc8000d decoder needs them as a separate codec-config buffer. */
static int build_config(const unsigned char *au, int len, unsigned char *out,
                        int max) {
    int n = 0;
    for (int i = 0; i + 3 < len; ) {
        int sc = -1, sl = 0;
        if (au[i] == 0 && au[i + 1] == 0 && au[i + 2] == 1) { sc = i; sl = 3; }
        else if (au[i] == 0 && au[i + 1] == 0 && au[i + 2] == 0 &&
                 au[i + 3] == 1) { sc = i; sl = 4; }
        if (sc < 0) { i++; continue; }
        int j = sc + sl;
        int next = len;
        for (int k = j; k + 2 < len; k++) {
            if (au[k] == 0 && au[k + 1] == 0 && au[k + 2] == 1) { next = k; break; }
            if (k + 3 < len && au[k] == 0 && au[k + 1] == 0 &&
                au[k + 2] == 0 && au[k + 3] == 1) { next = k; break; }
        }
        int type = g_hevc ? ((au[j] >> 1) & 0x3F) : (au[j] & 0x1F);
        int want = g_hevc ? (type == 32 || type == 33 || type == 34)
                          : (type == 6 || type == 7 || type == 8);
        if (want) {
            int nl = next - sc;
            if (n + nl <= max) {
                for (int q = 0; q < nl; q++) out[n + q] = au[sc + q];
                n += nl;
            }
        }
        i = next;
    }
    return n;
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
    g_setup_tunnel = (OMX_ERRORTYPE (*)(OMX_HANDLETYPE, OMX_U32,
                                        OMX_HANDLETYPE, OMX_U32))
        pds(core, "OMX_SetupTunnel");
    if (!init || !get) return;
    init();
    g_omx_get = get;
    g_decode_only = (sys_faccessat(AT_FDCWD, DEC_PATH, 0) == 0);
    g_tunnel = !g_decode_only && (sys_faccessat(AT_FDCWD, TUNNEL_PATH, 0) == 0);
    int p720 = (sys_faccessat(AT_FDCWD, P720_PATH, 0) == 0);
    g_dec_w = p720 ? 1280 : 1920;
    g_dec_h = p720 ? 720 : 1080;
    int want_sink = !g_decode_only &&
                    ((sys_faccessat(AT_FDCWD, SINK_PATH, 0) == 0) ||
                     (sys_faccessat(AT_FDCWD, FORK_PATH, 0) == 0));
    int is_child = 0;

    /* Optional fork test: the child kills the UI parent so its gfx plane
     * releases, then the child keeps the video plane. Requires h264live_fork. */
    if (sys_faccessat(AT_FDCWD, FORK_PATH, 0) == 0) {
        typedef int (*fork_fn)(void);
        typedef int (*setsid_fn)(void);
        typedef int (*prctl_fn)(int, unsigned long, unsigned long, unsigned long, unsigned long);
        typedef int (*getppid_fn)(void);
        typedef int (*kill_fn)(int, int);
        typedef int (*close_fn)(int);
        fork_fn pf = (fork_fn)g_dlsym(RTLD_DEFAULT, "fork");
        setsid_fn pss = (setsid_fn)g_dlsym(RTLD_DEFAULT, "setsid");
        prctl_fn ppr = (prctl_fn)g_dlsym(RTLD_DEFAULT, "prctl");
        getppid_fn pgp = (getppid_fn)g_dlsym(RTLD_DEFAULT, "getppid");
        kill_fn pk = (kill_fn)g_dlsym(RTLD_DEFAULT, "kill");
        close_fn pclose = (close_fn)g_dlsym(RTLD_DEFAULT, "close");
        if (pf && pss && ppr && pgp && pk) {
            int c = pf();
            if (c > 0) {
                for (;;) { struct timespec_t t = { 0, 1000000000 }; sys_nanosleep(&t, 0); }
            } else if (c == 0) {
                is_child = 1;
                pss();
                ppr(15, (unsigned long)"n3hlive", 0, 0, 0); /* PR_SET_NAME */
                /* Close inherited display/gfx fds, kill the UI parent, then
                 * open the video plane immediately, exactly like the probe. */
                if (pclose) {
                    for (int fd = 3; fd < 1024; fd++) pclose(fd);
                }
                pk(pgp(), 9);
                NTLOG("fork child: UI parent killed, inherited fds closed");
                if (want_sink) {
                    int sr = sink_init();
                    NTLOG_INT("sink=", sr);
                    if (sr == 0) sink_maybe_nolut();
                }
            }
        }
    }

    if (want_sink && !is_child) {
        NTLOG("sink init begin");
        int sr = sink_init();
        NTLOG_INT("sink=", sr);
        if (sr == 0) sink_maybe_nolut();
    }

    if (!g_tunnel && g_sink_on && g_pcreate) {
        g_q_stop = 0;
        g_pq_head = g_pq_tail = g_pq_count = 0;
        for (int p = 0; p < MAXP; p++)
            for (int i = 0; i < NBUF; i++) g_pending[p][i] = 0;
        unsigned long tid;
        int tr = g_pcreate(&tid, 0, sink_thread, 0);
        NTLOG_INT("sink thread=", tr);
    }

    int want_hw = (sys_faccessat(AT_FDCWD, HW_PATH, 0) == 0);
    int want_hevc = (sys_faccessat(AT_FDCWD, HEVC_PATH, 0) == 0);
    g_hevc = want_hevc;
    const char *dnames[6];
    int dn = 0;
    if (want_hevc) {
        dnames[dn++] = "OMX.dji.video_decoder.hevc.vc8000d";
        dnames[dn++] = "OMX.dji.video_decoder.hevc.ffmpeg";
        dnames[dn++] = "OMX.dji.video_decoder.h265.vc8000d";
    }
    if (!want_hevc) {
        if (want_hw) dnames[dn++] = "OMX.dji.video_decoder.avc.vc8000d";
        dnames[dn++] = "OMX.dji.video_decoder.avc.ffmpeg";
    }

    OMX_ERRORTYPE e = OMX_ErrorUndefined;
    int sel = -1;
    for (int i = 0; i < dn; i++) {
        e = get(&g_comp, (OMX_STRING)dnames[i], 0, &g_cbs);
        NTLOG_INT("dec try=", i);
        NTLOG_INT("  ret=", (int)e);
        if (e == OMX_ErrorNone && g_comp) { sel = i; break; }
        g_comp = 0;
    }
    if (sel < 0) { NTLOG("no decoder"); return; }
    g_planar = n3_contains(dnames[sel], "ffmpeg") ? 1 : 0;
    NTLOG_INT("dec sel=", sel);
    NTLOG_INT("planar=", g_planar);
    NTLOG_INT("hevc=", g_hevc);

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
            pd.format.video.nFrameWidth = g_dec_w;
            pd.format.video.nFrameHeight = g_dec_h;
            pd.format.video.eCompressionFormat =
                g_hevc ? (OMX_VIDEO_CODINGTYPE)0x7F000001 : OMX_VIDEO_CodingAVC;
            if (pd.nBufferSize < MAX_AU) pd.nBufferSize = MAX_AU;
        } else {
            pd.format.video.nFrameWidth = g_dec_w;
            pd.format.video.nFrameHeight = g_dec_h;
            pd.format.video.nStride = g_dec_w;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
        }
        OMX_U32 nb = (p == 0) ? 16 : 7;
        if (pd.nBufferCountMin > nb) nb = pd.nBufferCountMin;
        if (nb > 16) nb = 16;
        pd.nBufferCountActual = nb;
        OMX_SetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT(p == 0 ? "in size=" : "out size=", (int)pd.nBufferSize);
        NTLOG_INT(p == 0 ? "in min=" : "out min=", (int)pd.nBufferCountMin);
        NTLOG_INT(p == 0 ? "in n=" : "out n=", (int)pd.nBufferCountActual);
        if (p == 0) g_in_alloc = (long)pd.nBufferSize;
        if (p == 1) {
            g_dec_stride = (int)pd.format.video.nStride;
            g_dec_slice = (int)pd.format.video.nSliceHeight;
            if (g_dec_stride < FB_W) g_dec_stride = FB_W;
            if (g_dec_slice < FB_H) g_dec_slice = FB_H;
            NTLOG_INT("out stride=", g_dec_stride);
            NTLOG_INT("out slice=", g_dec_slice);
            NTLOG_INT("out fmt=", (int)pd.format.video.eColorFormat);
            NTLOG_INT("dec cs=", set_colorspace(g_comp, port, 2 /*BT601*/));
        }
        nb = pd.nBufferCountActual;
        if (nb < 1) nb = 4;
        if (nb > 16) nb = 16;
        for (OMX_U32 i = 0; i < nb; i++) {
            if (g_tunnel && p == 1) break;   /* output port is tunneled */
            OMX_BUFFERHEADERTYPE *bh = 0;
            OMX_U32 bsize = pd.nBufferSize;
            if (p == 0 && bsize < MAX_AU) bsize = MAX_AU;
            OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &bh, port, 0, bsize);
            if (a != OMX_ErrorNone && bsize != pd.nBufferSize) {
                bsize = pd.nBufferSize;
                a = OMX_AllocateBuffer(g_comp, &bh, port, 0, bsize);
            }
            if (a != OMX_ErrorNone) { NTLOG_INT("alloc err=", (int)a); break; }
            if (p == 0) g_in_alloc = (long)bsize;
            if (p == 0) g_ib[g_ni++] = bh; else g_ob[g_no++] = bh;
        }
    }
    NTLOG_INT("in bufs=", g_ni);
    NTLOG_INT("out bufs=", g_no);
    if (!g_ni || (!g_tunnel && !g_no)) { teardown(); return; }

    if (g_tunnel) {
        OMX_ERRORTYPE te = g_setup_tunnel
            ? g_setup_tunnel(g_comp, g_out_port, g_sink, g_sink_ports[0])
            : OMX_ErrorUndefined;
        NTLOG_INT("tunnel=", (int)te);
        g_state_ok = 0; g_err = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        NTLOG_INT("idle=", g_state_ok);
        g_sink_state_ok = 0; g_sink_err = 0;
        OMX_SendCommand(g_sink, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 300 && !g_sink_state_ok && !g_sink_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        NTLOG_INT("sink idle=", g_sink_state_ok);
        g_state_ok = 0; g_err = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
        for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        NTLOG_INT("exec=", g_state_ok);
        g_sink_state_ok = 0; g_sink_err = 0;
        OMX_SendCommand(g_sink, OMX_CommandStateSet, OMX_StateExecuting, 0);
        for (int i = 0; i < 300 && !g_sink_state_ok && !g_sink_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        NTLOG_INT("sink exec=", g_sink_state_ok);
    } else {
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
    }

    if (!g_decode_only && !g_sink_on) g_display = (display_init() == 0);
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
        if (g_in_alloc > 0 && (long)len > g_in_alloc) {
            NTLOG_INT("AU too big, skip=", (int)len);
            continue;
        }
        while ((sent - g_empty_calls) >= g_ni) { struct timespec_t t={0,2000000}; sys_nanosleep(&t,0); }
        if (!g_planar && !g_cfg_done) {
            OMX_BUFFERHEADERTYPE *cb = g_ib[in_i % g_ni];
            int cl = build_config(au, (int)len, cb->pBuffer, (int)g_in_alloc);
            if (cl > 0) {
                cb->nFilledLen = cl;
                cb->nOffset = 0;
                cb->nFlags = OMX_BUFFERFLAG_CODECCONFIG;
                cb->nTimeStamp = g_ts;
                OMX_EmptyThisBuffer(g_comp, cb);
                in_i++; sent++;
                g_cfg_done = 1;
                NTLOG_INT("cfg=", cl);
                while ((sent - g_empty_calls) >= g_ni) {
                    struct timespec_t t={0,2000000}; sys_nanosleep(&t,0);
                }
            }
        }
        OMX_BUFFERHEADERTYPE *ib = g_ib[in_i % g_ni];
        for (unsigned i = 0; i < len; i++) ib->pBuffer[i] = au[i];
        ib->nFilledLen = len;
        ib->nOffset = 0;
        ib->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
        ib->nTimeStamp = g_ts;
        g_ts += 16666;
        OMX_EmptyThisBuffer(g_comp, ib);
        in_i++; sent++;
        if (g_tunnel) {
            sink_push_sub();
            g_tun_frames++;
            if ((g_tun_frames % 60) == 0) {
                g_frames = g_tun_frames;
                g_sink_sent = g_tun_frames;
                put_stat();
            }
        }
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
    g_pcreate = pc;
    unsigned long tid;
    pc(&tid, 0, (void *(*)(void *))worker, 0);
    return 0;
}
