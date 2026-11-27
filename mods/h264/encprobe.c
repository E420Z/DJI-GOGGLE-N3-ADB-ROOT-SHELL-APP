/*
 * n3encprobe - feed the live LCDC YUV channel into a second vc8000e encoder
 * at 60 Mbps and dump the elementary stream. Bounded and self-cleaning.
 *
 * Safety:
 *   - reads zv900_liveview_lcdc_chn (read-only MDC subscription)
 *   - opens a second encoder instance; never touches the display pipeline
 *   - writes only /data/local/tmp/enc_hi.h264
 *   - 3 s / 24 MB cap, then Idle + free buffers + FreeHandle
 *   - one shot: removes /data/local/tmp/enc_on on exit
 */
#define NTLOG_PREFIX "enc"
#include "natartos_common.h"

#include <OMX_Types.h>
#include <OMX_Core.h>
#include <OMX_Component.h>
#include <OMX_Video.h>
#include <OMX_IVCommon.h>
#include <OMX_Index.h>

typedef void *(*dlsym_fn)(void *, const char *);
typedef void *(*dlopen_fn)(const char *, int);
typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);

#define RTLD_NOW 2
#define ARM_PATH "/data/local/tmp/enc_on"
#define OUT_PATH "/data/local/tmp/enc_hi.h264"
#define __NR_unlinkat 35

static inline long sys_unlink(const char *p) {
    register long x0 __asm__("x0") = AT_FDCWD;
    register long x1 __asm__("x1") = (long)p;
    register long x2 __asm__("x2") = 0;
    register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
#define CHAN_JSON "{\"channel_id\":1,\"device\":\"local_mdc\"," \
                  "\"name\":\"zv900_liveview_lcdc_chn\",\"type\":0}"
#define W 1920
#define H 1080
#define BITRATE 60000000
#define IN_BUFS 4
#define OUT_BUFS 4
#define OUT_CAP (24L * 1024 * 1024)

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_rd, g_enc;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_rd_state, g_enc_state, g_err;
static volatile long g_in_frames, g_out_frames, g_out_bytes, g_dropped;
static volatile int g_lock;
static int g_fd = -1;
static long g_ts;
static int g_capped;

static OMX_BUFFERHEADERTYPE *g_in[IN_BUFS];
static volatile int g_in_busy[IN_BUFS];
static int g_in_n;
static OMX_BUFFERHEADERTYPE *g_ob[OUT_BUFS];
static int g_out_n;
static OMX_BUFFERHEADERTYPE *g_rb[4];
static int g_rd_n;
static OMX_U32 g_rd_port;
static long g_enc_in_size;

static unsigned char g_csd[512];
static int g_csd_len;
static int g_synth = -1;

static void lock(void) { while (__sync_lock_test_and_set(&g_lock, 1)) __asm__ volatile("yield"); }
static void unlock(void) { __sync_lock_release(&g_lock); }

static void ver(void *p, unsigned n) {
    OMX_U32 *u = (OMX_U32 *)p;
    u[0] = n;
    OMX_VERSIONTYPE *v = (OMX_VERSIONTYPE *)(u + 1);
    v->s.nVersionMajor = 1; v->s.nVersionMinor = 0;
    v->s.nRevision = 0; v->s.nStep = 0;
}

static OMX_ERRORTYPE ev(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                        OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) {
        if (h == g_rd) g_rd_state = 1; else g_enc_state = 1;
    }
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event err=", (int)d1); }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE empty_cb(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a;
    lock();
    for (int i = 0; i < g_in_n; i++) if (g_in[i] == b) g_in_busy[i] = 0;
    unlock();
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE fill_cb(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    if (b->nFilledLen) {
        g_out_frames++;
        g_out_bytes += (long)b->nFilledLen;
        if (b->nFlags & OMX_BUFFERFLAG_CODECCONFIG) {
            long n = (long)b->nFilledLen;
            if (n > (long)sizeof(g_csd)) n = sizeof(g_csd);
            for (long i = 0; i < n; i++) g_csd[i] = b->pBuffer[b->nOffset + i];
            g_csd_len = (int)n;
            NTLOG_INT("csd=", g_csd_len);
        } else if (g_fd >= 0 && !g_capped) {
            if (g_out_bytes > OUT_CAP) {
                g_capped = 1;
                NTLOG("output cap reached, draining only");
            } else {
                long off = 0;
                while (off < (long)b->nFilledLen) {
                    long w = sys_write_raw(g_fd, b->pBuffer + b->nOffset + off,
                                           (long)b->nFilledLen - off);
                    if (w <= 0) break;
                    off += w;
                }
            }
        }
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { ev, empty_cb, fill_cb };

static OMX_ERRORTYPE rd_fill(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    if (!b->nFilledLen) { OMX_FillThisBuffer(h, b); return OMX_ErrorNone; }
    g_in_frames++;
    int idx = -1;
    lock();
    for (int i = 0; i < g_in_n; i++) if (!g_in_busy[i]) { g_in_busy[i] = 1; idx = i; break; }
    unlock();
    if (idx < 0) {
        g_dropped++;
        OMX_FillThisBuffer(h, b);
        return OMX_ErrorNone;
    }
    OMX_BUFFERHEADERTYPE *in = g_in[idx];
    long rlen = (long)b->nFilledLen;
    long ysz = (long)W * H;
    long uvsz = (long)W * H / 2;
    long copied;
    if (g_synth < 0)
        g_synth = sys_faccessat(AT_FDCWD, "/data/local/tmp/enc_synth", 0) == 0;
    if (g_synth) {
        /* moving high-detail pattern: measures the encoder's bitrate ceiling */
        unsigned char *p = in->pBuffer;
        for (long i = 0; i < g_enc_in_size; i++)
            p[i] = (unsigned char)((i * 7 + g_in_frames * 11) & 0xFF);
        copied = g_enc_in_size;
    } else if (rlen <= g_enc_in_size) {
        for (long i = 0; i < rlen; i++) in->pBuffer[i] = b->pBuffer[b->nOffset + i];
        copied = rlen;
    } else {
        long padded_h = (rlen * 2) / (3L * W);
        long uv_off = (long)W * padded_h;
        long n1 = ysz < g_enc_in_size ? ysz : g_enc_in_size;
        for (long i = 0; i < n1; i++) in->pBuffer[i] = b->pBuffer[b->nOffset + i];
        long room = g_enc_in_size - n1;
        long n2 = uvsz < room ? uvsz : room;
        for (long i = 0; i < n2; i++)
            in->pBuffer[n1 + i] = b->pBuffer[b->nOffset + uv_off + i];
        copied = n1 + n2;
    }
    in->nFilledLen = copied;
    in->nOffset = 0;
    in->nFlags = 0;
    in->nTimeStamp = g_ts;
    g_ts += 16666;
    OMX_EmptyThisBuffer(g_enc, in);
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_rd_cbs = { ev, empty_cb, rd_fill };

static void teardown(void) {
    if (g_rd) {
        g_rd_state = 0;
        OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_rd_state; i++) { struct timespec_t t = {0, 10000000}; sys_nanosleep(&t, 0); }
        for (int i = 0; i < g_rd_n; i++) {
            if (g_rb[i]) OMX_FreeBuffer(g_rd, g_rd_port, g_rb[i]);
            g_rb[i] = 0;
        }
        g_rd_n = 0;
        if (g_free_handle) g_free_handle(g_rd);
        g_rd = 0;
        NTLOG("reader closed");
    }
    if (g_enc) {
        g_enc_state = 0;
        OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 150 && !g_enc_state; i++) { struct timespec_t t = {0, 10000000}; sys_nanosleep(&t, 0); }
        for (int i = 0; i < g_in_n; i++) {
            if (g_in[i]) OMX_FreeBuffer(g_enc, 0, g_in[i]);
            g_in[i] = 0;
        }
        for (int i = 0; i < g_out_n; i++) {
            if (g_ob[i]) OMX_FreeBuffer(g_enc, 1, g_ob[i]);
            g_ob[i] = 0;
        }
        g_in_n = g_out_n = 0;
        if (g_free_handle) g_free_handle(g_enc);
        g_enc = 0;
        NTLOG("encoder closed");
    }
    if (g_fd >= 0) { sys_close(g_fd); g_fd = -1; }
    sys_unlink(ARM_PATH);
}

static void worker(void) {
    int waited = 0;
    while (waited < 1800) {
        if (sys_faccessat(AT_FDCWD, ARM_PATH, 0) == 0) break;
        struct timespec_t t = { 0, 100000000 };
        sys_nanosleep(&t, 0);
        waited++;
    }
    if (waited >= 1800) return;
    NTLOG("armed");
    g_synth = sys_faccessat(AT_FDCWD, "/data/local/tmp/enc_synth", 0) == 0;
    NTLOG_INT("synthetic=", g_synth);

    dlopen_fn pdl = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pds = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    void *core = pdl ? pdl("libOmxCore.so", RTLD_NOW) : 0;
    if (!core) { NTLOG("no core"); return; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))pds(core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        pds(core, "OMX_GetHandle");
    g_free_handle = (OMX_ERRORTYPE (*)(OMX_HANDLETYPE))pds(core, "OMX_FreeHandle");
    if (!init || !get) { NTLOG("no entry"); return; }
    init();

    /* ---- encoder ---- */
    OMX_ERRORTYPE e = get(&g_enc, "OMX.dji.video_encoder.avc.vc8000e", 0, &g_cbs);
    NTLOG_INT("enc=", (int)e);
    if (e != OMX_ErrorNone) { g_enc = 0; return; }

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    for (OMX_U32 p = 0; p < 2; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT("enc port=", (int)p);
        NTLOG_INT("  dir=", (int)pd.eDir);
        NTLOG_INT("  size=", (int)pd.nBufferSize);
        NTLOG_INT("  w=", (int)pd.format.video.nFrameWidth);
        NTLOG_INT("  h=", (int)pd.format.video.nFrameHeight);
        if (pd.eDir == OMX_DirInput) {
            pd.format.video.nFrameWidth = W;
            pd.format.video.nFrameHeight = H;
            pd.format.video.nStride = W;
            pd.format.video.nSliceHeight = H;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
            pd.nBufferCountActual = IN_BUFS;
            NTLOG_INT("  set in=", (int)OMX_SetParameter(
                g_enc, OMX_IndexParamPortDefinition, &pd));
        } else {
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingAVC;
            pd.format.video.nFrameWidth = W;
            pd.format.video.nFrameHeight = H;
            pd.nBufferCountActual = OUT_BUFS;
            NTLOG_INT("  set out=", (int)OMX_SetParameter(
                g_enc, OMX_IndexParamPortDefinition, &pd));
        }
    }

    OMX_VIDEO_PARAM_BITRATETYPE br;
    for (unsigned i = 0; i < sizeof(br); i++) ((unsigned char *)&br)[i] = 0;
    ver(&br, sizeof(br)); br.nPortIndex = 1;
    br.eControlRate = OMX_Video_ControlRateVariable;
    br.nTargetBitrate = BITRATE;
    NTLOG_INT("bitrate=", (int)OMX_SetParameter(g_enc, OMX_IndexParamVideoBitrate, &br));

    OMX_CONFIG_FRAMERATETYPE fr;
    for (unsigned i = 0; i < sizeof(fr); i++) ((unsigned char *)&fr)[i] = 0;
    ver(&fr, sizeof(fr)); fr.nPortIndex = 1; fr.xEncodeFramerate = 60 << 16;
    NTLOG_INT("fps=", (int)OMX_SetParameter(g_enc, OMX_IndexConfigVideoFramerate, &fr));

    g_enc_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc idle=", g_enc_state);
    if (!g_enc_state) goto out;

    for (int p = 0; p < 2; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
        if (p == 0) g_enc_in_size = (long)pd.nBufferSize;
        int cnt = p == 0 ? IN_BUFS : OUT_BUFS;
        for (int i = 0; i < cnt; i++) {
            OMX_BUFFERHEADERTYPE *bh = 0;
            OMX_ERRORTYPE a = OMX_AllocateBuffer(g_enc, &bh, p, 0, pd.nBufferSize);
            if (a != OMX_ErrorNone) { NTLOG_INT("alloc err=", (int)a); break; }
            if (p == 0) g_in[g_in_n++] = bh;
            else g_ob[g_out_n++] = bh;
        }
    }
    NTLOG_INT("in bufs=", g_in_n);
    NTLOG_INT("out bufs=", g_out_n);
    if (!g_in_n || !g_out_n) goto out;

    g_enc_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc exec=", g_enc_state);
    if (!g_enc_state) goto out;
    for (int i = 0; i < g_out_n; i++) OMX_FillThisBuffer(g_enc, g_ob[i]);

    /* ---- reader ---- */
    e = get(&g_rd, "OMX.dji.video_reader.mdc", 0, &g_rd_cbs);
    NTLOG_INT("rd=", (int)e);
    if (e != OMX_ErrorNone) { g_rd = 0; goto out; }

    static unsigned char uri_buf[512];
    for (unsigned i = 0; i < sizeof(uri_buf); i++) uri_buf[i] = 0;
    OMX_PARAM_CONTENTURITYPE *uri = (OMX_PARAM_CONTENTURITYPE *)uri_buf;
    const char *json = CHAN_JSON;
    int jl = 0; while (json[jl]) jl++;
    uri->nSize = sizeof(OMX_PARAM_CONTENTURITYPE) + jl;
    uri->nVersion.s.nVersionMajor = 1;
    for (int i = 0; i <= jl; i++) uri->contentURI[i] = (OMX_U8)json[i];
    NTLOG_INT("uri=", (int)OMX_SetParameter(g_rd, OMX_IndexParamContentURI, uri));

    g_rd_port = 0;
    int found = 0;
    for (OMX_U32 p = 0; p < 3; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        if (OMX_GetParameter(g_rd, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone) continue;
        if (pd.eDir == OMX_DirOutput) { g_rd_port = p; found = 1; break; }
    }
    if (!found) { NTLOG("no reader port"); goto out; }
    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = g_rd_port;
    OMX_GetParameter(g_rd, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("rd size=", (int)pd.nBufferSize);

    g_rd_state = 0; g_err = 0;
    OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_rd_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("rd idle=", g_rd_state);
    if (!g_rd_state) goto out;

    for (int i = 0; i < 3; i++) {
        OMX_BUFFERHEADERTYPE *bh = 0;
        if (OMX_AllocateBuffer(g_rd, &bh, g_rd_port, 0, pd.nBufferSize) != OMX_ErrorNone) break;
        g_rb[g_rd_n++] = bh;
    }
    NTLOG_INT("rd bufs=", g_rd_n);
    if (!g_rd_n) goto out;

    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241, 0644);
    NTLOG_INT("fd=", g_fd);

    g_rd_state = 0; g_err = 0;
    OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_rd_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("rd exec=", g_rd_state);
    if (!g_rd_state) goto out;

    for (int i = 0; i < g_rd_n; i++) OMX_FillThisBuffer(g_rd, g_rb[i]);
    NTLOG("capturing (3 s)");
    for (int i = 0; i < 30; i++) { struct timespec_t t={0,100000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("in frames=", (int)g_in_frames);
    NTLOG_INT("out frames=", (int)g_out_frames);
    NTLOG_INT("out bytes=", (int)g_out_bytes);
    NTLOG_INT("dropped=", (int)g_dropped);

out:
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
