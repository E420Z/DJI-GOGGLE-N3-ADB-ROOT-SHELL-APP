/*
 * n3input - raw input event logger (diagnostic only).
 *
 * Reads /dev/input/event0..3 read-only and appends EV_KEY events to
 * /data/local/tmp/n3_input.log as:
 *
 *     ev0 t1 c116 v1 ms123456
 *
 * No hooks, no grab, no display changes. Load it alone (not with n3menu) so
 * the stock UI keeps working while you press each control.
 */
#define NTLOG_PREFIX "n3in"
#include "natartos_common.h"

#define O_NONBLOCK 0x800
#define O_APPEND 02000
#define EV_KEY 1
#define LOG_PATH "/data/local/tmp/n3_input.log"

struct input_event_t { long sec, usec; unsigned short type, code; int value; };

static const char *EV[4] = {
    "/dev/input/event0", "/dev/input/event1",
    "/dev/input/event2", "/dev/input/event3"
};

static long now_ms(void) {
    struct timespec_t t;
    register long x0 __asm__("x0") = 1;
    register long x1 __asm__("x1") = (long)&t;
    register long x8 __asm__("x8") = 113;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return (long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int put_int(char *b, int i, long v) {
    char d[16];
    int n = 0;
    if (v < 0) { b[i++] = '-'; v = -v; }
    if (v == 0) d[n++] = '0';
    while (v > 0) { d[n++] = (char)('0' + v % 10); v /= 10; }
    while (n > 0) b[i++] = d[--n];
    return i;
}

static void log_ev(int dev, unsigned short type, unsigned short code, int value) {
    char b[128];
    int i = 0;
    b[i++] = 'e'; b[i++] = 'v'; i = put_int(b, i, dev);
    b[i++] = ' '; b[i++] = 't'; i = put_int(b, i, type);
    b[i++] = ' '; b[i++] = 'c'; i = put_int(b, i, code);
    b[i++] = ' '; b[i++] = 'v'; i = put_int(b, i, value);
    b[i++] = ' '; b[i++] = 'm'; b[i++] = 's'; i = put_int(b, i, now_ms());
    b[i++] = '\n';
    int fd = (int)sys_openat(AT_FDCWD, LOG_PATH,
                             O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) {
        sys_write_raw(fd, b, i);
        sys_close(fd);
    }
}

static void *thread_fn(void *arg) {
    (void)arg;
    NTLOG("thread: start");
    int fds[4] = { -1, -1, -1, -1 };
    for (int i = 0; i < 4; i++)
        fds[i] = (int)sys_openat(AT_FDCWD, EV[i], O_RDONLY | O_NONBLOCK, 0);
    while (1) {
        for (int i = 0; i < 4; i++) {
            if (fds[i] < 0) {
                fds[i] = (int)sys_openat(AT_FDCWD, EV[i],
                                         O_RDONLY | O_NONBLOCK, 0);
                continue;
            }
            struct input_event_t ev;
            while (sys_read(fds[i], &ev, sizeof(ev)) == (long)sizeof(ev)) {
                if (ev.type == EV_KEY)
                    log_ev(i, ev.type, ev.code, ev.value);
            }
        }
        sys_nanosleep_ms(10);
    }
    return 0;
}

typedef int (*pthread_create_fn)(unsigned long *, const void *, void *(*)(void *), void *);
typedef void *(*dlsym_fn)(void *, const char *);

int natartos_mod_init(void *(*loader_dlsym)(void *, const char *)) {
    dlsym_fn g = (dlsym_fn)loader_dlsym;
    pthread_create_fn pc = g ? (pthread_create_fn)g(RTLD_DEFAULT, "pthread_create") : 0;
    if (!pc) { NTLOG("no pthread_create"); return -1; }
    unsigned long tid;
    int ret = pc(&tid, 0, thread_fn, 0);
    NTLOG_INT("pthread_create ret=", ret);
    return ret == 0 ? 0 : -1;
}
