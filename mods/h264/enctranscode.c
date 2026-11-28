/*
 * n3enctranscode - feed a hardware vc8000d decoder into a second vc8000e at
 * 60 Mbps and dump the elementary stream.
 *
 * Purpose: measure the encoder's real bitrate ceiling with high-entropy
 * content, without a live air unit. Decoder input is an Annex-B H.264 file
 * whose access units are paced at 60 fps.
 *
 * Safety: read-only OMX graph, writes only /data/local/tmp/enc_trans.h264.
 * Bounded, one shot, removes /data/local/tmp/trans_on and the lock on exit.
 */
#define NTLOG_PREFIX "etr"
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
#define ARM_PATH "/data/local/tmp/trans_on"
#define IN_PATH "/data/local/tmp/trans_in.h264"
#define OUT_PATH "/data/local/tmp/enc_trans.h264"
#define LOCK_PATH "/data/local/tmp/trans_lock"
#define __NR_unlinkat 35

#define W 1920
#define H 1080
#define STRIDE 2048
#define BITRATE 60000000
#define IN_BUFS 16
#define OUT_BUFS 4
#define MAX_AU (1024 * 1024)
#define FILE_CAP (32L * 1024 * 1024)
#define FEED_AUS 320

static inline long sys_unlink(const char *p) {
    register long x0 __asm__("x0") = AT_FDCWD;
    register long x1 __asm__("x1") = (long)p;
    register long x2 __asm__("x2") = 0;
    register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_dec, g_enc;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static OMX_ERRORTYPE (*g_setup_tunnel)(OMX_HANDLETYPE, OMX_U32,
                                       OMX_HANDLETYPE, OMX_U32);
static volatile int g_dec_state, g_enc_state, g_err;
static volatile int g_empty_calls;
static volatile long g_out_frames, g_out_bytes;
static int g_fd = -1;
static OMX_BUFFERHEADERTYPE *g_ib[IN_BUFS];
static int g_ni;
static OMX_BUFFERHEADERTYPE *g_ob[OUT_BUFS];
static int g_no;
static OMX_U32 g_dec_port, g_enc_in_port, g_enc_out_port;

static unsigned char g_file[FILE_CAP];

static void ver(void *p, unsigned n) {
    OMX_U32 *u = (OMX_U32 *)p;
    u[0] = n;
    OMX_VERSIONTYPE *v = (OMX_VERSIONTYPE *)(u + 1);
    v->s.nVersionMajor = 1; v->s.nVersionMinor = 0;
    v->s.nRevision = 0; v->s.nStep = 0;
}

static void write_all(const unsigned char *p, long n) {
    if (g_fd < 0) return;
    long off = 0;
    while (off < n) {
        long w = sys_write_raw(g_fd, p + off, n - off);
        if (w <= 0) break;
        off += w;
    }
}

static OMX_ERRORTYPE ev(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                        OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) {
        if (h == g_dec) g_dec_state = 1; else g_enc_state = 1;
    }
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event err=", (int)d1); }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE empty_cb(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b;
    g_empty_calls++;
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE fill_cb(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    if (b->nFilledLen) {
        if (!(b->nFlags & OMX_BUFFERFLAG_CODECCONFIG)) {
            g_out_frames++;
            write_all(b->pBuffer + b->nOffset, (long)b->nFilledLen);
        } else {
            write_all(b->pBuffer + b->nOffset, (long)b->nFilledLen);
        }
        g_out_bytes += (long)b->nFilledLen;
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { ev, empty_cb, fill_cb };

static void teardown(void) {
    if (g_dec) {
        g_dec_state = 0;
        OMX_SendCommand(g_dec, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_dec_state; i++) {
            struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
        }
        for (int i = 0; i < g_ni; i++) {
            if (g_ib[i]) OMX_FreeBuffer(g_dec, 0, g_ib[i]);
            g_ib[i] = 0;
        }
        g_ni = 0;
        if (g_free_handle) g_free_handle(g_dec);
        g_dec = 0;
        NTLOG("decoder closed");
    }
    if (g_enc) {
        g_enc_state = 0;
        OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 150 && !g_enc_state; i++) {
            struct timespec_t t = { 0, 10000000 }; sys_nanosleep(&t, 0);
        }
        for (int i = 0; i < g_no; i++) {
            if (g_ob[i]) OMX_FreeBuffer(g_enc, 1, g_ob[i]);
            g_ob[i] = 0;
        }
        g_no = 0;
        if (g_free_handle) g_free_handle(g_enc);
        g_enc = 0;
        NTLOG("encoder closed");
    }
    if (g_fd >= 0) { sys_close(g_fd); g_fd = -1; }
    sys_unlink(LOCK_PATH);
    sys_unlink(ARM_PATH);
}

/* NAL start search: returns index of the next 00 00 01 at/after from. */
static int next_start(const unsigned char *p, int len, int from) {
    for (int i = from; i + 3 < len; i++) {
        if (p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1) return i;
    }
    return len;
}

/* Copy SPS (7) / PPS (8) NALs into out, with start codes. */
static int build_config(const unsigned char *au, int len,
                        unsigned char *out, int max) {
    int n = 0;
    for (int i = 0; i + 4 < len; ) {
        int sc = next_start(au, len, i);
        if (sc >= len) break;
        int type = au[sc + 3] & 0x1F;
        int nx = next_start(au, len, sc + 3);
        int nl = nx - sc;
        if (type == 7 || type == 8) {
            if (n + nl <= max) {
                for (int q = 0; q < nl; q++) out[n + q] = au[sc + q];
                n += nl;
            }
        }
        i = nx;
    }
    return n;
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
    int lock_fd = (int)sys_openat(AT_FDCWD, LOCK_PATH,
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

    /* ---- encoder ---- */
    OMX_ERRORTYPE e = get(&g_enc, "OMX.dji.video_encoder.avc.vc8000e", 0, &g_cbs);
    NTLOG_INT("enc=", (int)e);
    if (e != OMX_ErrorNone || !g_enc) { g_enc = 0; return; }

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    for (OMX_U32 p = 0; p < 2; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
        if (pd.eDir == OMX_DirInput) {
            g_enc_in_port = p;
            pd.format.video.nFrameWidth = W;
            pd.format.video.nFrameHeight = H;
            pd.format.video.nStride = STRIDE;
            pd.format.video.nSliceHeight = H;
            pd.format.video.xFramerate = 60 << 16;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
            pd.nBufferCountActual = OUT_BUFS;
        } else {
            g_enc_out_port = p;
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

    /* mode 0 = storage (pipe builder map: storage 0, liveview 1). */
    OMX_PARAM_U32TYPE u32;
    for (unsigned i = 0; i < sizeof(u32); i++) ((unsigned char *)&u32)[i] = 0;
    ver(&u32, sizeof(u32));
    u32.nPortIndex = g_enc_out_port;
    u32.nU32 = 0;
    NTLOG_INT("mode0 ret=", (int)OMX_SetParameter(
        g_enc, (OMX_INDEXTYPE)0x7f000026, &u32));

    /* encoder output buffers before Idle */
    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = g_enc_out_port;
    OMX_GetParameter(g_enc, OMX_IndexParamPortDefinition, &pd);
    for (int i = 0; i < OUT_BUFS; i++) {
        OMX_BUFFERHEADERTYPE *bh = 0;
        if (OMX_AllocateBuffer(g_enc, &bh, g_enc_out_port, 0, pd.nBufferSize) != OMX_ErrorNone) break;
        g_ob[g_no++] = bh;
    }
    NTLOG_INT("out bufs=", g_no);
    if (!g_no) { teardown(); return; }

    /* ---- decoder ---- */
    e = get(&g_dec, "OMX.dji.video_decoder.avc.vc8000d", 0, &g_cbs);
    NTLOG_INT("dec=", (int)e);
    if (e != OMX_ErrorNone || !g_dec) { g_dec = 0; teardown(); return; }

    OMX_U32 dec_in = 0;
    g_dec_port = 1;
    for (OMX_U32 p = 0; p < 3; p++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = p;
        if (OMX_GetParameter(g_dec, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone) continue;
        if (pd.eDir == OMX_DirInput) dec_in = p; else g_dec_port = p;
    }
    for (int p = 0; p < 2; p++) {
        OMX_U32 port = p == 0 ? dec_in : g_dec_port;
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        ver(&pd, sizeof(pd)); pd.nPortIndex = port;
        OMX_GetParameter(g_dec, OMX_IndexParamPortDefinition, &pd);
        pd.format.video.nFrameWidth = W;
        pd.format.video.nFrameHeight = H;
        if (p == 0) {
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingAVC;
            if (pd.nBufferSize < MAX_AU) pd.nBufferSize = MAX_AU;
            pd.nBufferCountActual = IN_BUFS;
        } else {
            pd.format.video.nStride = STRIDE;
            pd.format.video.nSliceHeight = H;
            pd.format.video.xFramerate = 60 << 16;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
            pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
            pd.nBufferCountActual = 7;
        }
        NTLOG_INT(p == 0 ? "dec in set=" : "dec out set=",
                  (int)OMX_SetParameter(g_dec, OMX_IndexParamPortDefinition, &pd));
    }

    /* decoder input buffers */
    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = dec_in;
    OMX_GetParameter(g_dec, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("dec in size=", (int)pd.nBufferSize);
    for (int i = 0; i < IN_BUFS; i++) {
        OMX_BUFFERHEADERTYPE *bh = 0;
        OMX_U32 bsize = pd.nBufferSize < MAX_AU ? MAX_AU : pd.nBufferSize;
        OMX_ERRORTYPE a = OMX_AllocateBuffer(g_dec, &bh, dec_in, 0, bsize);
        if (a != OMX_ErrorNone && bsize != pd.nBufferSize) {
            a = OMX_AllocateBuffer(g_dec, &bh, dec_in, 0, pd.nBufferSize);
        }
        if (a != OMX_ErrorNone) { NTLOG_INT("dec alloc err=", (int)a); break; }
        g_ib[g_ni++] = bh;
    }
    NTLOG_INT("in bufs=", g_ni);
    if (!g_ni) { teardown(); return; }

    for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
    ver(&pd, sizeof(pd)); pd.nPortIndex = g_dec_port;
    OMX_GetParameter(g_dec, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("dec out stride=", (int)pd.format.video.nStride);
    NTLOG_INT("dec out slice=", (int)pd.format.video.nSliceHeight);
    NTLOG_INT("dec out size=", (int)pd.nBufferSize);

    if (!g_setup_tunnel) { NTLOG("no setup tunnel"); teardown(); return; }
    OMX_ERRORTYPE te = g_setup_tunnel(g_dec, g_dec_port, g_enc, g_enc_in_port);
    NTLOG_INT("tunnel=", (int)te);

    /* ---- load input ---- */
    int infd = (int)sys_openat(AT_FDCWD, IN_PATH, 0, 0);
    long flen = 0;
    if (infd >= 0) {
        flen = sys_read(infd, g_file, FILE_CAP);
        sys_close(infd);
    }
    NTLOG_INT("file len=", (int)flen);
    if (flen < 1024) { teardown(); return; }

    g_dec_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc idle=", g_enc_state);
    g_dec_state = 0; g_err = 0;
    OMX_SendCommand(g_dec, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_dec_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("dec idle=", g_dec_state);
    if (!g_enc_state || !g_dec_state) { teardown(); return; }

    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241, 0644);
    g_enc_state = 0; g_err = 0;
    OMX_SendCommand(g_enc, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_enc_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("enc exec=", g_enc_state);
    g_dec_state = 0; g_err = 0;
    OMX_SendCommand(g_dec, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_dec_state && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("dec exec=", g_dec_state);
    for (int i = 0; i < g_no; i++) OMX_FillThisBuffer(g_enc, g_ob[i]);

    /* ---- feed AUs (paced at 60 fps) ---- */
    int first = next_start(g_file, (int)flen, 0);
    if (first >= (int)flen) { first = 0; }
    int cfg_done = 0;
    int in_i = 0, sent = 0, aus = 0;
    NTLOG("feeding");
    for (int pos = first; pos < (int)flen && aus < FEED_AUS; ) {
        int nx = next_start(g_file, (int)flen, pos + 3);
        if (nx >= (int)flen) nx = (int)flen;
        /* an AU starts at an AUD (type 9); otherwise send NAL by NAL */
        int is_aud = ((g_file[pos + 3] & 0x1F) == 9);
        int au_end = nx;
        if (is_aud) {
            /* extend to the next AUD */
            int q = nx;
            for (;;) {
                if (q >= (int)flen) { au_end = (int)flen; break; }
                int t = g_file[q + 3] & 0x1F;
                if (t == 9) { au_end = q; break; }
                q = next_start(g_file, (int)flen, q + 3);
                if (q >= (int)flen) { au_end = (int)flen; break; }
            }
        }
        int len = au_end - pos;
        if (len <= 0 || len > MAX_AU) break;
        while (g_ni > 0 && (sent - g_empty_calls) >= g_ni) {
            struct timespec_t t = { 0, 2000000 }; sys_nanosleep(&t, 0);
        }
        if (!cfg_done) {
            OMX_BUFFERHEADERTYPE *cb = g_ib[in_i % g_ni];
            int cl = build_config(g_file + pos, len, cb->pBuffer, (int)MAX_AU);
            if (cl > 0) {
                cb->nFilledLen = cl;
                cb->nOffset = 0;
                cb->nFlags = OMX_BUFFERFLAG_CODECCONFIG;
                OMX_EmptyThisBuffer(g_dec, cb);
                in_i++; sent++;
                cfg_done = 1;
                NTLOG_INT("cfg=", cl);
            }
        }
        OMX_BUFFERHEADERTYPE *ib = g_ib[in_i % g_ni];
        for (int i = 0; i < len; i++) ib->pBuffer[i] = g_file[pos + i];
        ib->nFilledLen = len;
        ib->nOffset = 0;
        ib->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
        ib->nTimeStamp = (OMX_TICKS)aus * 16666;
        OMX_EmptyThisBuffer(g_dec, ib);
        in_i++; sent++;
        if (is_aud) aus++;
        pos = au_end;
        struct timespec_t t = { 0, 16666666 };
        sys_nanosleep(&t, 0);
        if ((aus % 60) == 0 && aus) {
            NTLOG_INT("aus=", aus);
            NTLOG_INT("  out frames=", (int)g_out_frames);
            NTLOG_INT("  out bytes=", (int)g_out_bytes);
        }
    }
    NTLOG("fed");
    for (int i = 0; i < 30; i++) { struct timespec_t t={0,100000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("out frames=", (int)g_out_frames);
    NTLOG_INT("out bytes=", (int)g_out_bytes);

    teardown();
    NTLOG("done");
}

int n3enctranscode_start(void *loader_dlsym) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    pthread_create_fn pc = (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!pc) return 1;
    unsigned long tid;
    pc(&tid, 0, (void *(*)(void *))worker, 0);
    return 0;
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    return n3enctranscode_start((void *)loader_dlsym);
}
