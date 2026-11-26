/*
 * n3mods.so - minimal Natartos mod loader for DJI Goggles N3.
 *
 * The N3 cannot create /vendor/natartos/mods (dji_services can write files in
 * existing dirs but cannot mkdir).  So mods live flat in /vendor and the app
 * passes a colon-separated list in N3_MODS.
 *
 * Build: zig cc -target aarch64-linux-gnu -shared -fPIC -nostdlib -O2
 *        -I natartos-src/include -Wl,-soname,n3mods.so -o n3mods.so n3mods.c
 */
#include "natartos_common.h"

#define RTLD_NOW 2
#define RTLD_NOLOAD 4
#define RTLD_GLOBAL 0x100

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern char *dlerror(void);
extern char *getenv(const char *name);
extern int dladdr(const void *addr, void *info);
extern int pthread_create(unsigned long *thread, const void *attr,
                          void *(*start)(void *), void *arg);
extern int usleep(unsigned int usec);

typedef struct {
    const char *dli_fname;
    void *dli_fbase;
    const char *dli_sname;
    void *dli_saddr;
} DlInfo;

/* The N3 object vtable pointers are loaded from GOT slots in the respective
 * __Init functions.  __vmt_* symbols are class descriptors, not object
 * vtables.  Both GOT slots are RELATIVE relocations, so they are valid as soon
 * as the library is mapped; the method slots inside the vtable are filled at
 * EW init time, which is why the mod patches them from a late thread. */
#define N3_MAIN_VMT_GOT 0x6316bf0UL
#define N3_MORE_VMT_GOT 0x6319460UL

static void log_line(const char *tag, const char *path);

static void *g_ew = 0;
static void *g_gfx = 0;
static void *g_disp = 0;
static void *g_main_vmt = 0;
static void *g_more_vmt = 0;
static unsigned long g_ew_base = 0;
static int (*g_late_init)(void) = 0;

static void refresh_vmts(void) {
    if (!g_ew_base) return;
    void *m = *(void **)(g_ew_base + N3_MAIN_VMT_GOT);
    void *o = *(void **)(g_ew_base + N3_MORE_VMT_GOT);
    if (m) g_main_vmt = m;
    if (o) g_more_vmt = o;
}

static void *late_thread(void *arg) {
    (void)arg;
    for (int i = 0; i < 120; i++) {
        usleep(250000);
        refresh_vmts();
        if (g_late_init && g_late_init()) {
            log_line("late vmt patch done", 0);
            break;
        }
    }
    return 0;
}

/* Resolver passed to mods: global scope first, then the EW/gfx handles.
 * The EW libraries are loaded RTLD_LOCAL by the DJI app, so plain
 * dlsym(RTLD_DEFAULT, ...) does not see EwNewStringAnsi / EwCreateBitmap. */
static void *n3_resolve(void *handle, const char *name) {
    if (!name) return 0;
    if (handle == (void *)0) {
        if (g_main_vmt &&
            natartos_strncmp(name, "__n3_main_menu_vmt", 64) == 0)
            return g_main_vmt;
        if (g_more_vmt &&
            natartos_strncmp(name, "__n3_more_menu_vmt", 64) == 0)
            return g_more_vmt;
    }
    if (handle == (void *)-1) {
        if (g_disp &&
            natartos_strncmp(name, "duss_hal_display_push_frame", 64) == 0)
            return dlsym(g_disp, name);
        if (g_ew && natartos_strncmp(name, "MxBindableAbstractMenu_Reload", 64) == 0)
            return dlsym(g_ew, name);
        return dlsym((void *)-1, name);
    }
    void *p = dlsym(handle, name);
    if (!p && handle == (void *)0) {
        if (g_gfx) p = dlsym(g_gfx, name);
        if (!p && g_ew) p = dlsym(g_ew, name);
    }
    return p;
}

typedef int (*mod_init_fn)(void *(*)(void *, const char *));
typedef int (*mod_register_fn)(void *(*)(void *, const char *));

static const char LOG[] = "/data/local/tmp/n3mods.log";

static void log_line(const char *tag, const char *path) {
    int fd = (int)sys_openat(AT_FDCWD, LOG, O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd < 0) return;
    sys_write_raw(fd, tag, natartos_strlen(tag));
    sys_write_raw(fd, " ", 1);
    if (path) sys_write_raw(fd, path, natartos_strlen(path));
    sys_write_raw(fd, "\n", 1);
    sys_close(fd);
}

static int read_mod_list(char *buf, int max) {
    int fd = (int)sys_openat(AT_FDCWD, "/data/local/tmp/n3mods.list", O_RDONLY, 0);
    if (fd < 0) return 0;
    int n = 0;
    for (;;) {
        long r = sys_read(fd, buf + n, max - 1 - n);
        if (r <= 0) break;
        n += (int)r;
        if (n >= max - 1) break;
    }
    sys_close(fd);
    buf[n] = 0;
    for (int i = 0; i < n; i++)
        if (buf[i] == '\n' || buf[i] == '\r' || buf[i] == ' ')
            buf[i] = ':';
    return n;
}

__attribute__((constructor))
static void n3mods_init(void) {
    char buf[1024];
    int n = 0;
    const char *list = getenv("N3_MODS");
    if (list && list[0]) {
        while (list[n] && n < (int)sizeof(buf) - 1) {
            buf[n] = list[n];
            n++;
        }
        buf[n] = 0;
    } else {
        n = read_mod_list(buf, sizeof(buf));
    }
    if (!n || !buf[0]) {
        log_line("no mod list", 0);
        return;
    }

    void *handles[16];
    int count = 0;
    char *p = buf;
    while (*p && count < 16) {
        char *q = p;
        while (*q && *q != ':') q++;
        if (*q) { *q = 0; q++; }
        if (*p) {
            void *h = dlopen(p, RTLD_NOW | RTLD_GLOBAL);
            log_line(h ? "loaded" : "FAILED", p);
            if (!h) {
                const char *e = dlerror();
                if (e) log_line("  reason", e);
            }
            if (h) handles[count++] = h;
        }
        p = q;
    }

    g_ew = dlopen("libew_gls.so", RTLD_NOW | RTLD_NOLOAD);
    if (!g_ew) g_ew = dlopen("/vendor/libew_gls.so", RTLD_NOW | RTLD_NOLOAD);
    if (!g_ew) g_ew = dlopen("/vendor/libew_gls.so", RTLD_NOW);
    log_line(g_ew ? "ew handle ok" : "ew handle FAILED", 0);

    if (g_ew) {
        void *reload = dlsym(g_ew, "MxBindableAbstractMenu_Reload");
        if (reload) {
            DlInfo info;
            if (dladdr(reload, &info) && info.dli_fbase) {
                g_ew_base = (unsigned long)info.dli_fbase;
                refresh_vmts();
                log_line(g_main_vmt ? "main vmt resolved" : "main vmt zero", 0);
                log_line(g_more_vmt ? "more vmt resolved" : "more vmt zero", 0);
            } else {
                log_line("dladdr failed", 0);
            }
        } else {
            log_line("reload symbol missing", 0);
        }
        if (!g_more_vmt) {
            g_more_vmt = dlsym(g_ew, "__vmt_DuThemedControlsMoreMenu");
            log_line("more vmt descriptor fallback", 0);
        }
    }

    g_gfx = dlopen("libewrte_gfx_soft.11.00.so", RTLD_NOW | RTLD_NOLOAD);
    if (!g_gfx) g_gfx = dlopen("/system/lib64/libewrte_gfx_soft.11.00.so",
                              RTLD_NOW | RTLD_NOLOAD);
    if (!g_gfx) g_gfx = dlopen("libewrte_gfx_soft.so", RTLD_NOW | RTLD_NOLOAD);
    if (!g_gfx) g_gfx = dlopen("/system/lib64/libewrte_gfx_soft.11.00.so",
                              RTLD_NOW);
    log_line(g_gfx ? "gfx handle ok" : "gfx handle FAILED", 0);

    g_disp = dlopen("libdisp_eng.so", RTLD_NOW | RTLD_NOLOAD);
    if (!g_disp) g_disp = dlopen("/system/lib64/libdisp_eng.so",
                                 RTLD_NOW | RTLD_NOLOAD);
    if (!g_disp) g_disp = dlopen("/system/lib64/libdisp_eng.so", RTLD_NOW);
    log_line(g_disp ? "disp handle ok" : "disp handle FAILED", 0);

    for (int i = 0; i < count; i++) {
        mod_init_fn init = (mod_init_fn)dlsym(handles[i], "natartos_mod_init");
        if (init) init(n3_resolve);
        mod_register_fn reg = (mod_register_fn)dlsym(handles[i], "natartos_mod_register");
        if (reg) reg(n3_resolve);
        if (!g_late_init) {
            void *late = dlsym(handles[i], "n3_menu_late_init");
            if (late) g_late_init = (int (*)(void))late;
        }
    }
    if (g_late_init) {
        unsigned long tid = 0;
        if (pthread_create(&tid, 0, late_thread, 0) != 0)
            log_line("late thread FAILED", 0);
        else
            log_line("late thread started", 0);
    }
    log_line("init done, mods=", 0);
}
