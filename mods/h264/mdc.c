/*
 * n3mdc - read the encoded app-liveview stream out of the vendor MDC source.
 *
 * Opens OMX.dji.video_reader.avc.mdc, points it at the zv900_app_liveview_chn
 * channel with OMX_IndexParamContentURI, and dumps the encoded H.264 to
 * /data/local/tmp/mdc.h264 for a few seconds.
 *
 * Armed by /data/local/tmp/mdc_on so the capture starts when we say.
 * Read-only consumer: it never starts or stops the media pipeline.
 */
#define NTLOG_PREFIX "mdc"
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

#define CHAN_JSON "{\"channel_id\":1,\"device\":\"local_mdc\"," \
                  "\"name\":\"zv900_app_liveview_chn\",\"type\":0}"
#define OUT_PATH "/data/local/tmp/mdc.h264"
#define CAPTURE_SECONDS 12
#define CAP_BYTES (8 * 1024 * 1024)

static dlsym_fn g_dlsym = 0;
static OMX_HANDLETYPE g_comp = 0;
static volatile int g_state_ok = 0;
static volatile int g_err = 0;
static volatile long g_bytes = 0;
static volatile int g_fills = 0;
static int g_fd = -1;
static unsigned char g_head[64];
static int g_head_len = 0;

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
    g_fills++;
    if (b->nFilledLen && g_bytes < CAP_BYTES) {
        long off = 0;
        while (off < (long)b->nFilledLen && g_bytes < CAP_BYTES) {
            long n = sys_write_raw(g_fd, b->pBuffer + b->nOffset + off,
                                   (long)b->nFilledLen - off);
            if (n <= 0) break;
            off += n;
            g_bytes += n;
        }
        if (g_head_len < 64) {
            int take = 64 - g_head_len;
            if (take > (int)b->nFilledLen) take = (int)b->nFilledLen;
            for (int i = 0; i < take; i++)
                g_head[g_head_len + i] = b->pBuffer[b->nOffset + i];
            g_head_len += take;
        }
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };

static void log_ports(void) {
    OMX_PARAM_PORTDEFINITIONTYPE pd;
    for (OMX_U32 i = 0; i < 3; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd);
        pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        NTLOG_INT("port=", (int)i);
        NTLOG_INT("  dir=", (int)pd.eDir);
        NTLOG_INT("  bufs=", (int)pd.nBufferCountActual);
        NTLOG_INT("  size=", (int)pd.nBufferSize);
        if (pd.eDomain == OMX_PortDomainVideo) {
            NTLOG_INT("  coding=", (int)pd.format.video.eCompressionFormat);
            NTLOG_INT("  w=", (int)pd.format.video.nFrameWidth);
            NTLOG_INT("  h=", (int)pd.format.video.nFrameHeight);
        }
    }
}

static void mdc_worker(void) {
    /* wait for the arm flag (up to 3 minutes) */
    int waited = 0;
    while (waited < 1800) {
        if (sys_faccessat(AT_FDCWD, "/data/local/tmp/mdc_on", 0) == 0) break;
        struct timespec_t ts = { 0, 100000000 };
        sys_nanosleep(&ts, 0);
        waited++;
    }
    if (waited >= 1800) { NTLOG("mdc: never armed"); return; }
    NTLOG("mdc: armed");

    dlopen_fn pdlopen = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pdlsym = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    if (!pdlopen || !pdlsym) { NTLOG("mdc: no dlopen"); return; }

    void *core = pdlopen("libOmxCore.so", RTLD_NOW);
    if (!core) { NTLOG("mdc: no core"); return; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))pdlsym(core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        pdlsym(core, "OMX_GetHandle");
    if (!init || !get) { NTLOG("mdc: no core entry"); return; }
    NTLOG_INT("mdc: init=", (int)init());

    OMX_ERRORTYPE e = get(&g_comp, "OMX.dji.video_reader.avc.mdc", 0, &g_cbs);
    NTLOG_INT("mdc: handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) return;

    log_ports();

    /* content URI carries the channel JSON */
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
    NTLOG_INT("mdc: set uri=", (int)OMX_SetParameter(
        g_comp, OMX_IndexParamContentURI, uri));

    /* find the output port */
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
    if (!found) { NTLOG("mdc: no output port"); return; }
    NTLOG_INT("mdc: out_port=", (int)out_port);

    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd);
    pd.nPortIndex = out_port;
    OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("mdc: bufsize=", (int)pd.nBufferSize);

    OMX_BUFFERHEADERTYPE *bufs[6];
    int n = 0;
    int want = (int)pd.nBufferCountActual;
    if (want > 6) want = 6;
    for (int i = 0; i < want; i++) {
        OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &bufs[i], out_port, 0,
                                             pd.nBufferSize);
        if (a != OMX_ErrorNone) { NTLOG_INT("mdc: alloc err=", (int)a); break; }
        n++;
    }
    NTLOG_INT("mdc: bufs=", n);
    if (!n) return;

    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241 /*O_WRONLY|CREAT|TRUNC*/, 0644);
    if (g_fd < 0) { NTLOG("mdc: cannot open out"); return; }

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    NTLOG_INT("mdc: to idle=", g_state_ok);
    if (!g_state_ok) return;

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) {
        struct timespec_t ts = { 0, 10000000 };
        sys_nanosleep(&ts, 0);
    }
    NTLOG_INT("mdc: to exec=", g_state_ok);
    if (!g_state_ok) return;

    for (int i = 0; i < n; i++) OMX_FillThisBuffer(g_comp, bufs[i]);

    NTLOG("mdc: capturing");
    for (int i = 0; i < CAPTURE_SECONDS * 10; i++) {
        struct timespec_t ts = { 0, 100000000 };
        sys_nanosleep(&ts, 0);
    }

    NTLOG_INT("mdc: fills=", g_fills);
    NTLOG_INT("mdc: bytes=", (int)g_bytes);
    NTLOG_INT("mdc: head_len=", g_head_len);
    if (g_head_len >= 4) {
        NTLOG_INT("mdc: b0=", g_head[0]);
        NTLOG_INT("mdc: b1=", g_head[1]);
        NTLOG_INT("mdc: b2=", g_head[2]);
        NTLOG_INT("mdc: b3=", g_head[3]);
    }
    if (g_fd >= 0) sys_close(g_fd);
    NTLOG("mdc: done");
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    if (!g_dlsym) return 1;
    pthread_create_fn pcreate =
        (pthread_create_fn)g_dlsym(RTLD_DEFAULT, "pthread_create");
    if (!pcreate) { NTLOG("mdc: no pthread"); return 1; }
    unsigned long tid;
    pcreate(&tid, 0, (void *(*)(void *))mdc_worker, 0);
    return 0;
}
