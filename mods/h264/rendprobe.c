/*
 * n3rendprobe - feed a moving NV12 test pattern into the Air Unit display sink.
 *
 * Tries OMX.dji.iv_renderer.yuv.extra_blending, then .liveview. Bounded to
 * ~10 s, full Idle/free/FreeHandle teardown. No framebuffer, no /system writes.
 * Armed by /data/local/tmp/rend_on.
 */
#define NTLOG_PREFIX "rend"
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
#define ARM_PATH "/data/local/tmp/rend_on"
#define FORK_PATH "/data/local/tmp/rend_fork"
#define __NR_unlinkat 35

static inline long sys_unlink(const char *p) {
    register long x0 __asm__("x0") = AT_FDCWD;
    register long x1 __asm__("x1") = (long)p;
    register long x2 __asm__("x2") = 0;
    register long x8 __asm__("x8") = __NR_unlinkat;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}
#define W 1920
#define H 1080
#define SUW 640
#define SUH 360
#define FBUF (W * H * 3 / 2)
#define SUFBUF (SUW * SUH * 3 / 2)
#define NBUF 7
#define MAXP 4

static dlsym_fn g_dlsym;
static OMX_HANDLETYPE g_comp;
static OMX_ERRORTYPE (*g_free_handle)(OMX_HANDLETYPE);
static volatile int g_state_ok, g_err;
static volatile int g_empty;
static OMX_U32 g_ports[MAXP];
static int g_np;
static OMX_BUFFERHEADERTYPE *g_buf[MAXP][NBUF];
static int g_bn[MAXP];

static void set_ver(OMX_PARAM_PORTDEFINITIONTYPE *pd) {
    pd->nSize = sizeof(*pd);
    pd->nVersion.s.nVersionMajor = 1;
    pd->nVersion.s.nVersionMinor = 0;
    pd->nVersion.s.nRevision = 0;
    pd->nVersion.s.nStep = 0;
}

/* The Air Unit pipeline passes this URL via OMX_SetParameter(0x0100000D).
 * Struct from PipeBuilder::setNodeUrl: nSize = len + 0xd, version 1, URL at +8. */
static void set_url(void) {
    static const char url[] =
        "{\"config_file\":\"/etc/display_frame_rate_map.json\","
        "\"enable_aux_liveview\":false,"
        "\"sub_stream_h_offset\":144,\"sub_stream_v_offset\":64,"
        "\"sub_stream_width\":496,\"sub_stream_height\":280,"
        "\"notify_sub_stream_alive_status\":true}";
    unsigned char buf[0x200];
    for (unsigned i = 0; i < sizeof(buf); i++) buf[i] = 0;
    int n = (int)sizeof(url) - 1;
    *(uint32_t *)buf = (uint32_t)(n + 0xd);
    *(uint32_t *)(buf + 4) = 1;
    for (int i = 0; i <= n; i++) buf[8 + i] = (unsigned char)url[i];
    OMX_ERRORTYPE e = OMX_SetParameter(g_comp, (OMX_INDEXTYPE)0x0100000D, buf);
    NTLOG_INT("url ret=", (int)e);
}

static OMX_ERRORTYPE ev(OMX_HANDLETYPE h, OMX_PTR a, OMX_EVENTTYPE e,
                        OMX_U32 d1, OMX_U32 d2, OMX_PTR ed) {
    (void)h; (void)a; (void)d2; (void)ed;
    if (e == OMX_EventCmdComplete && d1 == OMX_CommandStateSet) g_state_ok = 1;
    if (e == OMX_EventError) { g_err = (int)d1; NTLOG_INT("event err=", (int)d1); }
    return OMX_ErrorNone;
}
static OMX_ERRORTYPE emp(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b; g_empty++; return OMX_ErrorNone;
}
static OMX_ERRORTYPE fil(OMX_HANDLETYPE h, OMX_PTR a, OMX_BUFFERHEADERTYPE *b) {
    (void)h; (void)a; (void)b; return OMX_ErrorNone;
}
static OMX_CALLBACKTYPE g_cbs = { ev, emp, fil };

static void pattern(unsigned char *p, int frame) {
    unsigned char *y = p;
    unsigned char *uv = p + (long)W * H;
    int bar = (frame * 12) % (W + 400) - 400;
    for (int row = 0; row < H; row++) {
        unsigned char *r = y + (long)row * W;
        for (int x = 0; x < W; x++) {
            int black = (x >= bar && x < bar + 400) ||
                        (row >= (frame * 6) % H && row < (frame * 6) % H + 160);
            r[x] = black ? 16 : 235;
        }
    }
    for (long i = 0; i < (long)W * H / 2; i++) uv[i] = 128;
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

    /* Optional fork test: the child kills the UI parent so its gfx plane
     * releases, then the child keeps the video plane. Requires rend_fork. */
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
                pss();
                ppr(15, (unsigned long)"n3rend", 0, 0, 0); /* PR_SET_NAME */
                pk(pgp(), 9);                              /* SIGKILL the UI */
                /* The child inherited the UI's display/gfx fds. Close them so
                 * the gfx0 plane is released before we open the video plane. */
                if (pclose) {
                    for (int fd = 3; fd < 1024; fd++) pclose(fd);
                }
                NTLOG("fork child: UI parent killed, inherited fds closed");
            }
        }
    }

    const char *names[2] = { "OMX.dji.iv_renderer.yuv.extra_blending",
                             "OMX.dji.iv_renderer.yuv.liveview" };
    OMX_ERRORTYPE e = OMX_ErrorUndefined;
    for (int i = 0; i < 2 && !g_comp; i++) {
        e = get(&g_comp, (OMX_STRING)names[i], 0, &g_cbs);
        NTLOG_INT(i == 0 ? "extra_blending=" : "liveview=", (int)e);
        if (e != OMX_ErrorNone) g_comp = 0;
    }
    if (!g_comp) { NTLOG("no renderer"); return; }
    set_url();

    OMX_PARAM_PORTDEFINITIONTYPE pd;
    g_np = 0;
    for (OMX_U32 i = 0; i < 4; i++) {
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = i;
        if (OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd) != OMX_ErrorNone)
            continue;
        NTLOG_INT("port=", (int)i);
        NTLOG_INT("  dir=", (int)pd.eDir);
        NTLOG_INT("  size=", (int)pd.nBufferSize);
        NTLOG_INT("  w=", (int)pd.format.video.nFrameWidth);
        NTLOG_INT("  h=", (int)pd.format.video.nFrameHeight);
        NTLOG_INT("  color=", (int)pd.format.video.eColorFormat);
        if (pd.eDir == OMX_DirInput && g_np < MAXP) g_ports[g_np++] = i;
    }
    if (!g_np) { NTLOG("no input port"); goto out; }
    NTLOG_INT("input ports=", g_np);

    for (int p = 0; p < g_np; p++) {
        OMX_U32 port = g_ports[p];
        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        int pw = (p == 0) ? W : SUW;
        int ph = (p == 0) ? H : SUH;
        pd.format.video.nFrameWidth = pw;
        pd.format.video.nFrameHeight = ph;
        pd.format.video.nStride = pw;
        pd.format.video.nSliceHeight = ph;
        pd.format.video.eColorFormat = OMX_COLOR_FormatYUV420SemiPlanar;
        pd.format.video.eCompressionFormat = OMX_VIDEO_CodingUnused;
        pd.format.video.xFramerate = 60 << 16;
        pd.nBufferCountActual = NBUF;
        NTLOG_INT("set port=", (int)port);
        NTLOG_INT("  ret=", (int)OMX_SetParameter(
            g_comp, OMX_IndexParamPortDefinition, &pd));

        for (unsigned k = 0; k < sizeof(pd); k++) ((unsigned char *)&pd)[k] = 0;
        set_ver(&pd); pd.nPortIndex = port;
        OMX_GetParameter(g_comp, OMX_IndexParamPortDefinition, &pd);
        NTLOG_INT("  size now=", (int)pd.nBufferSize);
        for (int i = 0; i < NBUF; i++) {
            OMX_BUFFERHEADERTYPE *b = 0;
            OMX_ERRORTYPE a = OMX_AllocateBuffer(g_comp, &b, port, 0, pd.nBufferSize);
            if (a != OMX_ErrorNone) { NTLOG_INT("  alloc err=", (int)a); break; }
            g_buf[p][g_bn[p]++] = b;
        }
        NTLOG_INT("  bufs=", g_bn[p]);
    }
    for (int p = 0; p < g_np; p++) if (!g_bn[p]) goto out;

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("idle=", g_state_ok);
    if (!g_state_ok) goto out;

    g_state_ok = 0; g_err = 0;
    OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateExecuting, 0);
    for (int i = 0; i < 300 && !g_state_ok && !g_err; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
    NTLOG_INT("exec=", g_state_ok);
    if (!g_state_ok) goto out;

    int sent = 0;
    for (int f = 0; f < 600; f++) {
        for (int p = 0; p < g_np; p++) {
            OMX_BUFFERHEADERTYPE *b = g_buf[p][f % g_bn[p]];
            if (p == 0) {
                pattern(b->pBuffer, f);
                b->nFilledLen = FBUF;
            } else {
                for (long i = 0; i < (long)SUFBUF; i++) b->pBuffer[i] = 16;
                b->nFilledLen = SUFBUF;
            }
            b->nOffset = 0;
            b->nFlags = OMX_BUFFERFLAG_ENDOFFRAME;
            b->nTimeStamp = (OMX_TICKS)f * 16666;
            OMX_EmptyThisBuffer(g_comp, b);
            sent++;
        }
        struct timespec_t t = { 0, 16666000 }; sys_nanosleep(&t, 0);
    }
    NTLOG_INT("sent=", sent);
    NTLOG_INT("empty=", g_empty);

out:
    if (g_comp) {
        g_state_ok = 0;
        OMX_SendCommand(g_comp, OMX_CommandStateSet, OMX_StateIdle, 0);
        for (int i = 0; i < 100 && !g_state_ok; i++) { struct timespec_t t={0,10000000}; sys_nanosleep(&t,0); }
        for (int p = 0; p < g_np; p++) {
            for (int i = 0; i < g_bn[p]; i++) {
                if (g_buf[p][i]) OMX_FreeBuffer(g_comp, g_ports[p], g_buf[p][i]);
            }
        }
        if (g_free_handle) g_free_handle(g_comp);
        g_comp = 0;
        NTLOG("renderer closed");
    }
    sys_unlink(ARM_PATH);
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
