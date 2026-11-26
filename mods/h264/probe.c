/*
 * n3h264 - Stage B1: prove the OMX core works inside dji_glasses.
 *
 * Loads libOmxCore.so, initialises it, enumerates components and logs them.
 * Does NOT allocate buffers, touch the display or decode anything yet.
 *
 * Mod contract: export natartos_mod_init(); the loader passes its dlsym.
 *
 * Build (SDK):
 *   sdk\build.ps1 -Src ..\mods\h264\probe.c -Out ..\mods\h264\n3h264.so
 */
#define NTLOG_PREFIX "h264"
#include "natartos_common.h"

typedef void *(*dlsym_fn)(void *handle, const char *name);
typedef void *(*dlopen_fn)(const char *path, int mode);

#define RTLD_NOW 2
#define RTLD_DEFAULT ((void *)0)

typedef unsigned int OMX_U32;
typedef int OMX_ERRORTYPE;
typedef OMX_ERRORTYPE (*omx_init_fn)(void);
typedef OMX_ERRORTYPE (*omx_deinit_fn)(void);
typedef OMX_ERRORTYPE (*omx_enum_fn)(char *name, OMX_U32 name_len, OMX_U32 index);

static dlsym_fn g_dlsym = 0;
static char g_name[160];

static void log_name(const char *prefix, const char *name) {
    int i = 0;
    while (i < 150 && name[i]) { g_name[i] = name[i]; i++; }
    g_name[i] = 0;
    natartos_log_raw(prefix, g_name);
}

static int has_word(const char *s, const char *w) {
    for (int i = 0; s[i]; i++) {
        int k = 0;
        while (w[k] && s[i + k] == w[k]) k++;
        if (!w[k]) return 1;
    }
    return 0;
}

static void probe(void) {
    NTLOG("probe: start");
    if (!g_dlsym) { NTLOG("probe: no dlsym"); return; }

    dlopen_fn pdlopen = (dlopen_fn)g_dlsym(RTLD_DEFAULT, "dlopen");
    dlsym_fn pdlsym = (dlsym_fn)g_dlsym(RTLD_DEFAULT, "dlsym");
    if (!pdlopen || !pdlsym) { NTLOG("probe: dlopen/dlsym missing"); return; }

    void *core = pdlopen("libOmxCore.so", RTLD_NOW);
    if (!core) { NTLOG("probe: dlopen libOmxCore failed"); return; }
    NTLOG("probe: libOmxCore opened");

    omx_init_fn init = (omx_init_fn)pdlsym(core, "OMX_Init");
    omx_deinit_fn deinit = (omx_deinit_fn)pdlsym(core, "OMX_Deinit");
    omx_enum_fn enumerate = (omx_enum_fn)pdlsym(core, "OMX_ComponentNameEnum");
    if (!init || !enumerate) { NTLOG("probe: missing OMX entry points"); return; }

    OMX_ERRORTYPE err = init();
    NTLOG_INT("probe: OMX_Init err=", (int)err);
    if (err != 0) return;

    int count = 0, vdec = 0, venc = 0;
    for (OMX_U32 i = 0; i < 300; i++) {
        char name[128];
        if (enumerate(name, sizeof(name), i) != 0) break;
        count++;
        if (has_word(name, "decoder")) vdec++;
        if (has_word(name, "encoder")) venc++;
        if (i < 40) log_name(NTLOG_PREFIX, name);
    }
    NTLOG_INT("probe: components=", count);
    NTLOG_INT("probe: decoders=", vdec);
    NTLOG_INT("probe: encoders=", venc);

    if (deinit) deinit();
    NTLOG("probe: done");
}

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    g_dlsym = (dlsym_fn)loader_dlsym;
    probe();
    return 0;
}
