/*
 * n3videc - live-style H.264 decoder probe.
 *
 * Feeds one real access unit per buffer (no zero padding) with
 * OMX_BUFFERFLAG_ENDOFFRAME, then reports how many frames arrive BEFORE EOS.
 * That is the blocker for using the vendor decoder as a PC -> goggles path.
 *
 * Component: OMX.dji.video_decoder.avc.ffmpeg by default; create
 * /data/local/tmp/vdec_vc to try OMX.dji.video_decoder.avc.vc8000d.
 *
 * Input : /data/local/tmp/vdec_in.h264 (Annex-B, ideally no B-frames)
 * Output: /data/local/tmp/vdec_out.nv12 (first 8 frames)
 * Armed : /data/local/tmp/vdec_on
 */
#define NTLOG_PREFIX "vdec"
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
#define ARM_PATH "/data/local/tmp/vdec_on"
#define VC_PATH  "/data/local/tmp/vdec_vc"
#define IN_PATH  "/data/local/tmp/vdec_in.h264"
#define OUT_PATH "/data/local/tmp/vdec_out.nv12"
#define MAX_IN   (12 * 1024 * 1024)
#define MAX_OUT_FRAMES 8

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_comp;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_state_ok, g_err, g_eos;
static volatile int g_fill_calls, g_empty_calls, g_frames;
static volatile long g_bytes;
static int g_fd = -1;

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
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event err=", (int)d1); }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_empty(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b;
    g_empty_calls++;
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_fill(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)a;
    g_fill_calls++;
    if (b->nFilledLen) {
        g_frames++;
        g_bytes += (long)b->nFilledLen;
        if (g_frames <= 3) {
            NTLOG_INT("fill len=", (int)b->nFilledLen);
            NTLOG_INT("  flags=", (int)b->nFlags);
            NTLOG_INT("  ts=", (int)(b->nTimeStamp & 0x7fffffff));
            NTLOG_INT("  b0=", b->pBuffer[b->nOffset]);
            NTLOG_INT("  b1=", b->pBuffer[b->nOffset + 1]);
        }
        if (g_fd >= 0 && g_frames <= MAX_OUT_FRAMES) {
            long off = 0;
            while (off < (long)b->nFilledLen) {
                long w = sys_write_raw(g_fd, b->pBuffer + b->nOffset + off,
                                       (long)b->nFilledLen - off);
                if (w <= 0) break;
                off += w;
            }
        }
    }
    if (b->nFlags & OMX_BUFFERFLAG_EOS) g_eos = 1;
    if (!g_eos) OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };

static void teardown(OMX_U32 in_port, OMX_U32 out_port,
                     OMX_BUFFERHEADERTYPE **ib, int ni,
                     OMX_BUFFERHEADERTYPE **ob, int no) {
    if (g_comp) {
        g_state_ok = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_state_ok; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        for (int i = 0; i < ni; i++) if (ib[i]) OMX_FreeBuffer(g_comp, in_port, ib[i]);
        for (int i = 0; i < no; i++) if (ob[i]) OMX_FreeBuffer(g_comp, out_port, ob[i]);
        if (g_free_handle) g_free_handle(g_comp);
        g_comp = 0;
        NTLOG("component closed");
    }
    if (g_fd >= 0) { sys_close(g_fd); g_fd = -1; }
}

static void send_au(OMX_BUFFERHEADERTYPE *bu, const unsigned char *p, int len,
                    unsigned flags) {
    int cl = len;
    if (cl > (int)bu->nAllocLen) cl = (int)bu->nAllocLen;
    for (int k = 0; k < cl; k++) bu->pBuffer[k] = p[k];
    bu->nFilledLen = cl;
    bu->nOffset = 0;
    bu->nTimeStamp = (OMX_TICKS)(g_fill_calls * 16666);
    bu->nFlags = flags;
    OMX_EmptyThisBuffer(g_comp, bu);
}

static int is_start(const unsigned char *p, int i, int total, int *hdr) {
    if (i + 3 < total && p[i] == 0 && p[i+1] == 0 && p[i+2] == 1) { *hdr = i+3; return 3; }
    if (i + 4 < total && p[i] == 0 && p[i+1] == 0 && p[i+2] == 0 && p[i+3] == 1) { *hdr = i+4; return 4; }
    return 0;
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

    const char *name = "OMX.dji.video_decoder.avc.ffmpeg";
    int use_vc = sys_faccessat(AT_FDCWD, VC_PATH, 0) == 0;
    if (use_vc) name = "OMX.dji.video_decoder.avc.vc8000d";
    NTLOG_INT("vc=", use_vc);
    OMX_ERRORTYPE e = get(&g_comp, (OMX_STRING)name, 0, &g_cbs);
    NTLOG_INT("handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) { g_comp = 0; return; }

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    OMX_U32 in_port = 0, out_port = 1;
    for (OMX_U32 i = 0; i < 3; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd);
        pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        if (pd.eDomain != OMX_PortDomainVideo) continue;
        NTLOG_INT("port=", (int)i);
        NTLOG_INT("  dir=", (int)pd.eDir);
        NTLOG_INT("  size=", (int)pd.nBufferSize);
        NTLOG_INT("  coding=", (int)pd.format.video.eCompressionFormat);
        NTLOG_INT("  color=", (int)pd.format.video.eColorFormat);
        NTLOG_INT("  w=", (int)pd.format.video.nFrameWidth);
        NTLOG_INT("  h=", (int)pd.format.video.nFrameHeight);
        if (pd.eDir == OMX_DirInput) in_port = i; else out_port = i;
    }

    OMX_BUFFERHEADERTYPE *ib[4] = {0}, *ob[6] = {0};
    int ni = 0, no = 0;
    for (int p = 0; p < 2; p++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd);
        pd.nPortIndex = p == 0 ? in_port : out_port;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        if (p == 1) {
            pd.format.video.nFrameWidth = 1920;
            pd.format.video.nFrameHeight = 1080;
            pd.format.video.nStride = 1920;
            pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
            NTLOG_INT("set out=", (int)OMX_SetParameter(g_comp, OMX_IndexParamPortDefinition, &pd));
        }
        int cnt = p == 0 ? 4 : 6;
        for (int i = 0; i < cnt; i++) {
            OMX_BUFFERHEADERTYPE *bh = 0;
            if (OMX_AllocateBuffer(g_comp, &bh, pd.nPortIndex, 0, pd.nBufferSize) != OMX_ErrorNone) break;
            if (p == 0) ib[ni++] = bh; else ob[no++] = bh;
        }
    }
    NTLOG_INT("in bufs=", ni);
    NTLOG_INT("out bufs=", no);
    if (!ni || !no) { teardown(in_port, out_port, ib, ni, ob, no); return; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("idle=", g_state_ok);
    if (!g_state_ok) { teardown(in_port, out_port, ib, ni, ob, no); return; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("exec=", g_state_ok);
    if (!g_state_ok) { teardown(in_port, out_port, ib, ni, ob, no); return; }

    for (int i = 0; i < no; i++) OMX_FillThisBuffer(g_comp, ob[i]);

    static unsigned char src[MAX_IN];
    int fd = (int)sys_openat(AT_FDCWD, IN_PATH, 0, 0);
    if (fd < 0) { NTLOG("cannot open input"); teardown(in_port, out_port, ib, ni, ob, no); return; }
    int total = 0;
    for (;;) {
        long r = sys_read(fd, src + total, (long)sizeof(src) - total);
        if (r <= 0) break;
        total += (int)r;
        if (total >= (int)sizeof(src)) break;
    }
    sys_close(fd);
    NTLOG_INT("input bytes=", total);
    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241, 0644);

    /* Split into access units at AUD or at a VCL NAL after a previous VCL. */
    int au_start = -1, have_vcl = 0, sent = 0, in_i = 0;
    for (int i = 0; i + 3 < total; ) {
        int hdr = 0;
        if (!is_start(src, i, total, &hdr)) { i++; continue; }
        int nal = src[hdr] & 0x1f;
        int new_au = 0;
        if (nal == 9 && au_start >= 0) new_au = 1;                 /* AUD */
        if ((nal == 1 || nal == 5) && have_vcl) new_au = 1;         /* next picture */
        if (new_au) {
            while ((sent - g_empty_calls) >= ni) { struct timespec_t t={0,3000000}; sys_nanosleep(&t,0); }
            send_au(ib[in_i % ni], src + au_start, i - au_start,
                    OMX_BUFFERFLAG_ENDOFFRAME);
            in_i++; sent++;
            au_start = i; have_vcl = 0;
        } else if (au_start < 0) {
            au_start = i;
        }
        if (nal == 1 || nal == 5) have_vcl = 1;
        i = hdr + 1;
    }
    if (au_start >= 0) {
        while ((sent - g_empty_calls) >= ni) { struct timespec_t t={0,3000000}; sys_nanosleep(&t,0); }
        send_au(ib[in_i % ni], src + au_start, total - au_start,
                OMX_BUFFERFLAG_ENDOFFRAME);
        sent++;
    }
    NTLOG_INT("aus sent=", sent);

    /* Key question: do frames arrive BEFORE EOS? */
    for (int i = 0; i < 200 && !g_eos; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("pre_eos frames=", g_frames);
    NTLOG_INT("pre_eos fills=", g_fill_calls);
    NTLOG_INT("pre_eos bytes=", (int)g_bytes);
    NTLOG_INT("empty calls=", g_empty_calls);

    if (!g_eos) {
        OMX_BUFFERHEADERTYPE *be = ib[in_i % ni];
        be->nFilledLen = 0;
        be->nOffset = 0;
        be->nFlags = OMX_BUFFERFLAG_EOS;
        OMX_EmptyThisBuffer(g_comp, be);
    }
    for (int i = 0; i < 300 && !g_eos; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("eos=", g_eos);
    NTLOG_INT("final frames=", g_frames);
    NTLOG_INT("final fills=", g_fill_calls);
    NTLOG_INT("final bytes=", (int)g_bytes);

    teardown(in_port, out_port, ib, ni, ob, no);
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
