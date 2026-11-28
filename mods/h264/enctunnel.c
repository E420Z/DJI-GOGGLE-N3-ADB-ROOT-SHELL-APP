/*
 * n3enctunnel - LCDC YUV reader tunnelled into a second vc8000e at 60 Mbps.
 *
 * Bounded 3 s probe, writes /data/local/tmp/enc_tun.h264 (SPS/PPS + frames).
 * Read-only on the display pipeline; only /data/local/tmp is written.
 */
#define NTLOG_PREFIX "etun"
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
#define ARM_PATH "/data/local/tmp/enctun_on"
#define OUT_PATH "/data/local/tmp/enc_tun.h264"
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
#define STRIDE 2048
#define BITRATE 60000000
#define IN_BUFS 4
#define OUT_BUFS 4
#define OUT_CAP (24L * 1024 * 1024)

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_rd, g_enc;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static OMX_ERRORTYPE (*g_setup_tunnel)(OMX_HANDLETYPE, OMX_U32,
                                       OMX_HANDLETYPE, OMX_U32);
static volatile int g_rd_state, g_enc_state, g_err;
static volatile long g_out_frames, g_out_bytes;
static int g_fd = -1;
static int g_capped;
static OMX_BUFFERHEADERTYPE *g_ob[OUT_BUFS];
static int g_out_n;
static OMX_U32 g_rd_port;
static long g_ts;

static void ver(void *p, unsigned n) {
    OMX_U32 *u = (OMX_U32 *)p;
    u[0] = n;
    OMX_VERSIONTYPE *v = (OMX_VERSIONTYPE *)(u + 1);
    v->s.nVersionMajor = 1; v->s.nVersionMinor = 0;
    v->s.nRevision = 0; v->s.nStep = 0;
}

static void write_all(const unsigned char *p, long n) {
    if (g_fd < 0 || g_capped) return;
    long off = 0;
    while (off < n) {
        long w = sys_write_raw(g_fd, p + off, n - off);
        if (w <= 0) break;
        off += w;
    }
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
    (void)h; (void)a; (void)b; return OMX_ErrorNone;
}
static OMX_ERRORTYPE fill_cb(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    if (b->nFilledLen) {
        g_out_bytes += (long)b->nFilledLen;
        if (g_out_bytes > OUT_CAP) { g_capped = 1; }
        else if (!(b->nFlags & OMX_BUFFERFLAG_CODECCONFIG)) {
            write_all(b->pBuffer + b->nOffset, (long)b->nFilledLen);
            g_out_frames++;
        }
    }
    if (g_capped) {
        /* keep draining without writing */
    } else if (b->nFlags & OMX_BUFFERFLAG_CODECCONFIG) {
        write_all(b->pBuffer + b->nOffset, (long)b->nFilledLen);
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}
static OMX_CALLBACKTYPE g_cbs = { ev, empty_cb, fill_cb };

static OMX_ERRORTYPE rd_fill(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a; (void)b;
    /* tunnelled output: the encoder consumes it, no client Fill */
    (void)h;
    return OMX_ErrorNone;
}
static OMX_CALLBACKTYPE g_rd_cbs = { ev, empty_cb, rd_fill };

static void teardown(void) {
    if (g_rd) {
        g_rd_state = 0;
        OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_rd_state; i++) {
            struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
        }
        if (g_free_handle) g_free_handle(g_rd);
        g_rd = 0;
        NTLOG("reader closed");
    }
    if (g_enc) {
        g_enc_state = 0;
        OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 150 && !g_enc_state; i++) {
            struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
        }
        for (int i = 0; i < g_out_n; i++) {
            if (g_ob[i]) OMX_FreeBuffer(g_enc, 1, g_ob[i]);
            g_ob[i] = 0;
        }
        g_out_n = 0;
        if (g_free_handle) g_free_handle(g_enc);
        g_enc = 0;
        NTLOG("encoder closed");
    }
    if (g_fd >= 0) { sys_close(g_fd); g_fd = -1; }
    sys_unlink("/data/local/tmp/enctun_lock");
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
    /* Only one process may run the probe (the patched UI forks for the
     * PC-video sink). */
    int lock_fd = (int)sys_openat(AT_FDCWD, "/data/local/tmp/enctun_lock",
                                  0xC1 /* WRONLY|CREAT|EXCL */, 0644);
    if (lock_fd < 0) { NTLOG("duplicate instance, exit"); return; }
    sys_close(lock_fd);
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
    if (!init || !get) { NTLOG("no entry"); return; }
    init();

    /* encoder */
    OMX_ERRORTYPE e = get(&g_enc, "OMX.dji.video_encoder.avc.vc8000e", 0, &g_cbs);
    NTLOG_INT("enc=", (int)e);
    if (e != OMX_ErrorNone || !g_enc) { g_enc = 0; return; }

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    for (OMX_U32 p = 0; p < 2; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
        if (pd.eDir == OMX_DirInput) {
            pd.format.video.nFrameWidth = W;
            pd.format.video.nFrameHeight = H;
            pd.format.video.nStride = STRIDE;
            pd.format.video.nSliceHeight = H;
            pd.format.video.xFramerate = 60 << 16;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
            pd.nBufferCountActual = IN_BUFS;
        } else {
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingAVC;
            pd.format.video.nFrameWidth = W;
            pd.format.video.nFrameHeight = H;
            pd.format.video.nBitrate = BITRATE;
            pd.format.video.xFramerate = 60 << 16;
            pd.nBufferCountActual = OUT_BUFS;
        }
        NTLOG_INT(p == 0 ? "enc in set=" : "enc out set=",
                  (int)OMX_SetParameter(g_enc, OMX_IndexParamPortDefinition, &pd));
    }

    /* Mode 0 = "storage" (pipe builder map: liveview 1, storage 0,
     * vision_storage 1); the vendor liveview pipe runs in storage mode. */
    OMX_PARAM_U32TYPE u32;
    for (unsigned i = 0; i < sizeof(u32); i++) ((unsigned char *)&u32)[i] = 0;
    ver(&u32, sizeof(u32));
    u32.nPortIndex = 1;
    u32.nU32 = 0;
    NTLOG_INT("mode0 ret=", (int)OMX_SetParameter(
        g_enc, (OMX_INDEXTYPE)0x7f000026, &u32));

    /* Ask the encoder for 60 fps (the LCDC writeback runs at ~120 Hz). */
    OMX_CONFIG_FRAMERATETYPE fr;
    for (unsigned i = 0; i < sizeof(fr); i++) ((unsigned char *)&fr)[i] = 0;
    ver(&fr, sizeof(fr));
    fr.nPortIndex = 1;
    fr.xEncodeFramerate = 60 << 16;
    NTLOG_INT("fps out=", (int)OMX_SetConfig(
        g_enc, OMX_IndexConfigVideoFramerate, &fr));
    fr.nPortIndex = 0;
    NTLOG_INT("fps in=", (int)OMX_SetConfig(
        g_enc, OMX_IndexConfigVideoFramerate, &fr));

    /* IDR period (GOP); use spec version 1.1.2 in case the check is strict. */
    OMX_VIDEO_CONFIG_AVCINTRAPERIOD ip;
    for (unsigned i = 0; i < sizeof(ip); i++) ((unsigned char *)&ip)[i] = 0;
    ip.nSize = sizeof(ip);
    ip.nVersion.s.nVersionMajor = 1;
    ip.nVersion.s.nVersionMinor = 1;
    ip.nVersion.s.nRevision = 2;
    ip.nVersion.s.nStep = 0;
    ip.nPortIndex = 1;
    ip.nIDRPeriod = 60;
    ip.nPFrames = 59;
    NTLOG_INT("idr ret=", (int)OMX_SetConfig(
        g_enc, OMX_IndexConfigVideoAVCIntraPeriod, &ip));

    /* output buffers before Idle */
    for (OMX_U32 p = 0; p < 2; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT(p == 0 ? "enc in size=" : "enc out size=", (int)pd.nBufferSize);
        if (p == 0) continue;
        for (int i = 0; i < OUT_BUFS; i++) {
            OMX_BUFFERHEADERTYPE *bh = 0;
            if (OMX_AllocateBuffer(g_enc, &bh, p, 0, pd.nBufferSize) != OMX_ErrorNone) break;
            g_ob[g_out_n++] = bh;
        }
    }
    NTLOG_INT("out bufs=", g_out_n);
    if (!g_out_n) { teardown(); return; }

    /* reader */
    e = get(&g_rd, "OMX.dji.video_reader.mdc", 0, &g_rd_cbs);
    NTLOG_INT("rd=", (int)e);
    if (e != OMX_ErrorNone || !g_rd) { g_rd = 0; teardown(); return; }

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
    if (!found) { NTLOG("no reader port"); teardown(); return; }

    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = g_rd_port;
    OMX_GetParameter(g_rd, OMX_IndexParamPortDefinition, &pd);
    pd.format.video.nFrameWidth = W;
    pd.format.video.nFrameHeight = H;
    pd.format.video.nStride = STRIDE;
    pd.format.video.nSliceHeight = H;
    pd.format.video.xFramerate = 60 << 16;
    pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
    pd.nBufferCountActual = IN_BUFS;
    NTLOG_INT("rd set=", (int)OMX_SetParameter(g_rd, OMX_IndexParamPortDefinition, &pd));
    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = g_rd_port;
    OMX_GetParameter(g_rd, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("rd size=", (int)pd.nBufferSize);
    NTLOG_INT("rd stride=", (int)pd.format.video.nStride);
    NTLOG_INT("rd color=", (int)pd.format.video.eColorFormat);

    if (!g_setup_tunnel) { NTLOG("no setup tunnel"); teardown(); return; }
    OMX_ERRORTYPE te = g_setup_tunnel(g_rd, g_rd_port, g_enc, 0);
    NTLOG_INT("tunnel=", (int)te);

    g_enc_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc idle=", g_enc_state);
    g_rd_state = 0; g_err = 0;
    OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_rd_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("rd idle=", g_rd_state);
    if (!g_enc_state || !g_rd_state) { teardown(); return; }

    /* Read back the encoder output port: did nBitrate survive Idle? */
    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = 1;
    OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("out bitrate=", (int)pd.format.video.nBitrate);
    NTLOG_INT("out bufs n=", (int)pd.nBufferCountActual);

    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241, 0644);
    g_enc_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc exec=", g_enc_state);

    /* One post-start bitrate attempt with the target value. */
    OMX_VIDEO_PARAM_BITRATETYPE bt;
    for (unsigned i = 0; i < sizeof(bt); i++) ((unsigned char *)&bt)[i] = 0;
    ver(&bt, sizeof(bt));
    bt.nPortIndex = 0;
    bt.eControlRate = OMX_Video_ControlRateConstant;
    bt.nTargetBitrate = BITRATE;
    NTLOG_INT("post p0=", (int)OMX_SetConfig(
        g_enc, OMX_IndexParamVideoBitrate, &bt));

    g_rd_state = 0; g_err = 0;
    OMX_SendCommand(g_rd, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_rd_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("rd exec=", g_rd_state);
    for (int i = 0; i < g_out_n; i++) OMX_FillThisBuffer(g_enc, g_ob[i]);

    NTLOG("capturing (3 s)");
    for (int i = 0; i < 30; i++) { struct timespec_t t={0,100000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("out frames=", (int)g_out_frames);
    NTLOG_INT("out bytes=", (int)g_out_bytes);

    teardown();
    NTLOG("done");
}

int n3enctunnel_start(void *loader_dlsym) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    pthread_create_fn pc = (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!pc) return 1;
    unsigned long tid;
    pc(&tid, 0, (void *(*)(void *))worker, 0);
    return 0;
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    return n3enctunnel_start((void *)loader_dlsym);
}
