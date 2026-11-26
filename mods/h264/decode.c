/*
 * n3h264 - Stage B2a: hardware H.264 decode of a canned file.
 *
 * Opens OMX.dji.video_decoder.avc.ffmpeg through libOmxCore.so, decodes
 * /data/local/tmp/probe.h264 and writes the raw NV12 output to
 * /data/local/tmp/probe.nv12. No display involvement, no fb_shared.
 *
 * Everything runs on a worker thread so the loader/UI init is never blocked.
 *
 * Build: sdk\build.ps1 -Src ..\mods\h264\decode.c -Out ..\mods\h264\n3h264.so
 */
#define NTLOG_PREFIX "h264"
#include "natartos_common.h"

#include <OMX_Types.h>
#include <OMX_Core.h>
#include <OMX_Component.h>
#include <OMX_Video.h>
#include <OMX_Index.h>

typedef void *(*dlsym_fn)(void *handle, const char *name);
typedef void *(*dlopen_fn)(const char *path, int mode);
typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);

#define RTLD_NOW 2
#define RTLD_DEFAULT ((void *)0)

#define IN_PATH  "/data/local/tmp/probe.h264"
#define OUT_PATH "/data/local/tmp/probe.nv12"
#define MAX_IN   (8 * 1024 * 1024)

static dlsym_fn g_dlsym = 0;
static pthread_create_fn g_pcreate = 0;

static void *g_core = 0;
static dlsym_fn g_pdlsym = 0;
static OMX_HANDLETYPE g_comp = 0;

static volatile int g_state_ok = 0;
static volatile int g_eos = 0;
static volatile int g_out_frames = 0;
static volatile long g_out_bytes = 0;
static volatile int g_err_seen = 0;
static volatile int g_fill_calls = 0;
static volatile int g_empty_calls = 0;
static int g_out_fd = -1;

/* ---- helpers ------------------------------------------------------------ */

static void log_int(const char *label, int v) { NTLOG_INT(label, v); }

static int str_eq(const char *a, const char *b) {
    int i = 0;
    while (a[i] && b[i] && a[i] == b[i]) i++;
    return a[i] == b[i];
}

/* ---- OMX callbacks ------------------------------------------------------ */

static OMX_ERRORTYPE on_event(OMX_HANDLETYPE h, OMX_PTR app, OMX_EVENTTYPE e,
                              OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)app; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete) {
        if (d1 == OMX_CommandStateSet) g_state_ok = 1;
    } else if (e == OMX_EventError) {
        g_err_seen = (int)d1;
        NTLOG_INT("omx event error=", (int)d1);
    }
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_empty(OMX_HANDLETYPE h, OMX_PTR app, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)app; (void)b;
    g_empty_calls++;
    return OMX_ErrorNone;
}

static OMX_ERRORTYPE on_fill(OMX_HANDLETYPE h, OMX_PTR app, OMX_BUFFERHEADERTYPE *b) {
    (void)app;
    g_fill_calls++;
    if (b->nFilledLen && g_out_fd >= 0) {
        long off = 0;
        while (off < (long)b->nFilledLen) {
            long n = sys_write_raw(g_out_fd, b->pBuffer + b->nOffset + off,
                                   (long)b->nFilledLen - off);
            if (n <= 0) break;
            off += n;
        }
        g_out_bytes += (long)b->nFilledLen;
        g_out_frames++;
    }
    if (b->nFlags & OMX_BUFFERFLAG_EOS) g_eos = 1;
    if (!g_eos) OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };

/* ---- worker ------------------------------------------------------------- */

static OMX_ERRORTYPE wait_state(OMX_COMMANDTYPE cmd) {
    g_state_ok = 0;
    OMX_SendCommand(g_comp, cmd, 0, 0);
    for (int i = 0; i < 300 && !g_state_ok; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    return g_state_ok ? OMX_ErrorNone : OMX_ErrorTimeout;
}

static void set_ver(OMX_PARAM_PORTDEFINITIONTYPE *pd, int major, int minor, int rev) {
    pd->nSize = sizeof(*pd);
    pd->nVersion.s.nVersionMajor = (OMX_U8)major;
    pd->nVersion.s.nVersionMinor = (OMX_U8)minor;
    pd->nVersion.s.nRevision = (OMX_U8)rev;
    pd->nVersion.s.nStep = 0;
}

static void describe_port(OMX_U32 idx) {
    OMX_PARAM_PORTDEFINITIONTYPE pd;
    static const int vers[4][3] = { {1,0,0}, {1,1,0}, {1,1,1}, {1,1,2} };
    for (int v = 0; v < 4; v++) {
        for (unsigned i = 0; i < sizeof(pd); i++) ((unsigned char *)&pd)[i] = 0;
        set_ver(&pd, vers[v][0], vers[v][1], vers[v][2]);
        pd.nPortIndex = idx;
        OMX_ERRORTYPE e = OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT("ver try (0=100,1=110,2=111,3=112)=", v);
        log_int("  result=", (int)e);
        if (e == OMX_ErrorNone) break;
    }
    log_int("  dir=", (int)pd.eDir);
    log_int("  domain=", (int)pd.eDomain);
    log_int("  bufcount=", (int)pd.nBufferCountActual);
    log_int("  bufsize=", (int)pd.nBufferSize);
    if (pd.eDomain == OMX_PortDomainVideo) {
        log_int("  coding=", (int)pd.format.video.eCompressionFormat);
        log_int("  color=", (int)pd.format.video.eColorFormat);
        log_int("  w=", (int)pd.format.video.nFrameWidth);
        log_int("  h=", (int)pd.format.video.nFrameHeight);
    }
}

static void decode_worker(void) {
    NTLOG("b2a: worker start");
    g_pdlsym = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    dlopen_fn pdlopen = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    if (!pdlopen || !g_pdlsym) { NTLOG("b2a: no dlopen/dlsym"); return; }

    g_core = pdlopen("libOmxCore.so", RTLD_NOW);
    if (!g_core) { NTLOG("b2a: no core"); return; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))g_pdlsym(g_core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        g_pdlsym(g_core, "OMX_GetHandle");
    OMX_ERRORTYPE (*freeh)(OMX_HANDLETYPE) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE))g_pdlsym(g_core, "OMX_FreeHandle");
    if (!init || !get) { NTLOG("b2a: no core entry"); return; }
    log_int("b2a: core init=", (int)init());

    OMX_ERRORTYPE e = get(&g_comp, "OMX.dji.video_decoder.avc.ffmpeg", 0, &g_cbs);
    log_int("b2a: get handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) return;

    describe_port(0);
    describe_port(1);

    /* find the compressed input port and the raw output port */
    OMX_PARAM_PORTDEFINITIONTYPE pd;
    OMX_U32 in_port = 0, out_port = 1;
    for (OMX_U32 i = 0; i < 3; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        pd.nSize = sizeof(pd);
        pd.nVersion.nVersion = 0x00000101;
        pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        if (pd.eDomain != OMX_PortDomainVideo) continue;
        if (pd.eDir == OMX_DirInput) in_port = i;
        else out_port = i;
    }
    log_int("b2a: in_port=", (int)in_port);
    log_int("b2a: out_port=", (int)out_port);

    /* configure output: 1920x1080 NV12 */
    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd, 1, 0, 0);
    pd.nPortIndex = out_port;
    if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) == OMX_ErrorNone) {
        pd.format.video.nFrameWidth = 1920;
        pd.format.video.nFrameHeight = 1080;
        pd.format.video.nStride = 1920;
        pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
        pd.nBufferCountActual = 4;
        log_int("b2a: set out=", (int)OMX_SetParameter(
            g_comp, OMX_IndexParamPortDefinition, &pd));
    }

    /* allocate buffers */
    OMX_BUFFERHEADERTYPE *in_bufs[4];
    OMX_BUFFERHEADERTYPE *out_bufs[4];
    int n_in = 0, n_out = 0;

    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd, 1, 0, 0);
    pd.nPortIndex = in_port;
    OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
    log_int("b2a: in bufsize=", (int)pd.nBufferSize);
    int want_in = (int)pd.nBufferCountActual; if (want_in > 4) want_in = 4;
    for (int i = 0; i < want_in; i++) {
        OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &in_bufs[i], in_port, 0,
                                             pd.nBufferSize);
        if (a != OMX_ErrorNone) { log_int("b2a: alloc in err=", (int)a); break; }
        n_in++;
    }
    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd, 1, 0, 0);
    pd.nPortIndex = out_port;
    OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
    log_int("b2a: out bufsize=", (int)pd.nBufferSize);
    int want_out = (int)pd.nBufferCountActual; if (want_out > 4) want_out = 4;
    for (int i = 0; i < want_out; i++) {
        OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &out_bufs[i], out_port, 0,
                                             pd.nBufferSize);
        if (a != OMX_ErrorNone) { log_int("b2a: alloc out err=", (int)a); break; }
        n_out++;
    }
    log_int("b2a: in_bufs=", n_in);
    log_int("b2a: out_bufs=", n_out);
    if (!n_in || !n_out) return;

    /* proper sequence: Loaded -> Idle -> Executing, waiting on the callback */
    g_state_ok = 0;
    g_err_seen = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err_seen; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    log_int("b2a: to idle=", g_state_ok);
    if (!g_state_ok) { log_int("b2a: idle err=", g_err_seen); return; }

    g_state_ok = 0;
    g_err_seen = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err_seen; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    log_int("b2a: to exec=", g_state_ok);
    if (!g_state_ok) { log_int("b2a: exec err=", g_err_seen); return; }

    for (int i = 0; i < n_out; i++) {
        OMX_ERRORTYPE f = OMX_FillThisBuffer(g_comp, out_bufs[i]);
        if (i == 0) log_int("b2a: fill ret=", (int)f);
    }

    /* read the whole file */
    static unsigned char src[MAX_IN];
    int fd = (int)sys_openat(AT_FDCWD, IN_PATH, 0, 0);
    if (fd < 0) { NTLOG("b2a: cannot open probe.h264"); return; }
    int total = 0;
    for (;;) {
        long r = sys_read(fd, src + total, (long)sizeof(src) - total);
        if (r <= 0) break;
        total += (int)r;
        if (total >= (int)sizeof(src)) break;
    }
    sys_close(fd);
    log_int("b2a: input bytes=", total);

    g_out_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241 /*O_WRONLY|O_CREAT|O_TRUNC*/, 0644);

    /* Feed one access unit (frame) per buffer: this decoder consumes a single
     * picture from each EmptyThisBuffer. */
    int au_start = -1;
    int sent = 0;
    int in_i = 0;

#define SEND_AU(ptr, len) do {                                                 \
        int wait = 0;                                                          \
        while (wait < 1000 && (sent - g_empty_calls) >= n_in) {                \
            struct timespec_t ts = { 0, 5000000 };                             \
            sys_nanosleep(&ts, 0);                                             \
            wait += 5;                                                         \
        }                                                                      \
        OMX_BUFFERHEADERTYPE *bu = in_bufs[in_i % n_in];                       \
        int cl = (int)(len);                                                   \
        if (cl > (int)bu->nAllocLen) cl = (int)bu->nAllocLen;                  \
        for (int k = 0; k < cl; k++) bu->pBuffer[k] = (ptr)[k];                \
        for (int k = cl; k < (int)bu->nAllocLen; k++) bu->pBuffer[k] = 0;      \
        bu->nFilledLen = bu->nAllocLen;                                        \
        bu->nOffset = 0;                                                       \
        bu->nTimeStamp = (OMX_TICKS)(sent * 33333);                            \
        bu->nFlags = 0;                                                        \
        OMX_EmptyThisBuffer(g_comp, bu);                                       \
        in_i++; sent++;                                                        \
    } while (0)

    for (int i = 0; i + 3 < total; ) {
        int hdr = -1;
        if (src[i] == 0 && src[i + 1] == 0 && src[i + 2] == 1) {
            hdr = i + 3;
        } else if (i + 4 < total && src[i] == 0 && src[i + 1] == 0 &&
                   src[i + 2] == 0 && src[i + 3] == 1) {
            hdr = i + 4;
        }
        if (hdr < 0) { i++; continue; }

        int nal = src[hdr] & 0x1f;
        if (nal == 1 || nal == 5) {               /* VCL: start of a picture */
            if (au_start >= 0) SEND_AU(src + au_start, i - au_start);
            au_start = i;
        } else if (au_start < 0) {
            au_start = i;                         /* SPS/PPS/SEI prologue */
        }
        i = hdr + 1;
    }
    if (au_start >= 0) SEND_AU(src + au_start, total - au_start);
    log_int("b2a: aus_sent=", sent);

    if (n_in > 0) {                               /* final empty buffer, EOS */
        OMX_BUFFERHEADERTYPE *be = in_bufs[in_i % n_in];
        be->nFilledLen = 0;
        be->nOffset = 0;
        be->nFlags = OMX_BUFFERFLAG_EOS;
        OMX_EmptyThisBuffer(g_comp, be);
    }

    /* drain */
    for (int i = 0; i < 600 && !g_eos; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }

    log_int("b2a: fill_calls=", g_fill_calls);
    log_int("b2a: empty_calls=", g_empty_calls);
    log_int("b2a: frames=", g_out_frames);
    log_int("b2a: bytes=", (int)g_out_bytes);
    log_int("b2a: eos=", g_eos);
    log_int("b2a: err=", g_err_seen);

    if (g_out_fd >= 0) sys_close(g_out_fd);

    g_state_ok = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 100 && !g_state_ok; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    for (int i = 0; i < n_in; i++) OMX_FreeBuffer(g_comp, in_port, in_bufs[i]);
    for (int i = 0; i < n_out; i++) OMX_FreeBuffer(g_comp, out_port, out_bufs[i]);

    g_state_ok = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateLoaded, 0);
    for (int i = 0; i < 100 && !g_state_ok; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    if (freeh) freeh(g_comp);
    NTLOG("b2a: done");
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    if (!g_dlsym) return 1;
    g_pcreate = (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!g_pcreate) { NTLOG("b2a: no pthread_create"); return 1; }
    unsigned long tid;
    g_pcreate(&tid, 0, (void *(*)(void *))decode_worker, 0);
    return 0;
}
