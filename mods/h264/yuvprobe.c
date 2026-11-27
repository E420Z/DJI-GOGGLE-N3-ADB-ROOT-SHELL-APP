/*
 * n3yuv - read the raw 1080p YUV frames from zv900_liveview_lcdc_chn.
 * Read-only probe: opens OMX.dji.video_reader.mdc, dumps 2 frames, logs fps.
 */
#define NTLOG_PREFIX "yuv"
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
#define ARM_PATH "/data/local/tmp/yuv_on"
#define OUT_PATH "/data/local/tmp/yuv_probe.raw"
#define CAP_FRAMES 2
#define CHAN_JSON "{\"channel_id\":1,\"device\":\"local_mdc\"," \
                  "\"name\":\"zv900_liveview_lcdc_chn\",\"type\":0}"

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_comp;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_state_ok, g_err;
static volatile long g_fills, g_bytes;
static int g_fd = -1;
static int g_saved;

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
        g_fills++;
        g_bytes += (long)b->nFilledLen;
        if (g_saved < CAP_FRAMES && g_fd >= 0) {
            long off = 0;
            while (off < (long)b->nFilledLen) {
                long n = sys_write_raw(g_fd, b->pBuffer + b->nOffset + off,
                                       (long)b->nFilledLen - off);
                if (n <= 0) break;
                off += n;
            }
            g_saved++;
        }
        if (g_fills == 1) {
            NTLOG_INT("first len=", (int)b->nFilledLen);
            NTLOG_INT("b0=", b->pBuffer[b->nOffset]);
            NTLOG_INT("b1=", b->pBuffer[b->nOffset + 1]);
            NTLOG_INT("b100=", b->pBuffer[b->nOffset + 100]);
        }
    }
    OMX_FillThisBuffer(h, b);
    return OMX_ErrorNone;
}

static OMX_CALLBACKTYPE g_cbs = { on_event, on_empty, on_fill };

static void worker(void) {
    int waited = 0;
    while (waited < 1800) {
        if (sys_faccessat(AT_FDCWD, ARM_PATH, 0) == 0) break;
        struct timespec_t ts = { 0, 100000000 };
        sys_nanosleep(&ts, 0);
        waited++;
    }
    if (waited >= 1800) return;
    NTLOG("armed");

    dlopen_fn pdlopen = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pdlsym = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    void *core = pdlopen ? pdlopen("libOmxCore.so", RTLD_NOW) : 0;
    if (!core) { NTLOG("no core"); return; }
    OMX_ERRORTYPE (*init)(void) = (OMX_ERRORTYPE (*)(void))pdlsym(core, "OMX_Init");
    OMX_ERRORTYPE (*get)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *) =
        (OMX_ERRORTYPE (*)(OMX_HANDLETYPE *, OMX_STRING, OMX_PTR, OMX_CALLBACKTYPE *))
        pdlsym(core, "OMX_GetHandle");
    g_free_handle = (OMX_ERRORTYPE (*)(OMX_HANDLETYPE))pdlsym(core, "OMX_FreeHandle");
    if (!init || !get) { NTLOG("no core entry"); return; }
    init();

    OMX_ERRORTYPE e = get(&g_comp, "OMX.dji.video_reader.mdc", 0, &g_cbs);
    NTLOG_INT("handle=", (int)e);
    if (e != OMX_ErrorNone || !g_comp) return;

    static unsigned char uri_buf[512];
    for (unsigned i = 0; i < sizeof(uri_buf); i++) uri_buf[i] = 0;
    OMX_PARAM_CONTENTURITYPE *uri = (OMX_PARAM_CONTENTURITYPE *)uri_buf;
    const char *json = CHAN_JSON;
    int jl = 0; while (json[jl]) jl++;
    uri->nSize = sizeof(OMX_PARAM_CONTENTURITYPE) + jl;
    uri->nVersion.s.nVersionMajor = 1;
    uri->nVersion.s.nVersionMinor = 0;
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
    if (!found) { NTLOG("no out port"); return; }

    for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
    set_ver(&pd);
    pd.nPortIndex = out_port;
    OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
    NTLOG_INT("out port=", (int)out_port);
    NTLOG_INT("size=", (int)pd.nBufferSize);
    NTLOG_INT("coding=", (int)pd.format.video.eColorFormat);
    NTLOG_INT("w=", (int)pd.format.video.nFrameWidth);
    NTLOG_INT("h=", (int)pd.format.video.nFrameHeight);

    OMX_BUFFERHEADERTYPE *bufs[6];
    int n = 0, want = (int)pd.nBufferCountActual;
    if (want > 6) want = 6;
    for (int i = 0; i < want; i++) {
        if (OMX_AllocateBuffer(g_comp, &bufs[i], out_port, 0, pd.nBufferSize) != OMX_ErrorNone)
            break;
        n++;
    }
    NTLOG_INT("bufs=", n);
    if (!n) return;

    g_fd = (int)sys_openat(AT_FDCWD, OUT_PATH, 0x241, 0644);
    NTLOG_INT("fd=", g_fd);

    g_state_ok = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("idle=", g_state_ok);
    g_state_ok = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("exec=", g_state_ok);
    if (!g_state_ok) return;

    for (int i = 0; i < n; i++) OMX_FillThisBuffer(g_comp, bufs[i]);
    NTLOG("capturing");
    for (int i = 0; i < 30; i++) { struct timespec_t t={0,100000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("fills=", (int)g_fills);
    NTLOG_INT("bytes=", (int)g_bytes);
    if (g_fd >= 0) sys_close(g_fd);
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
