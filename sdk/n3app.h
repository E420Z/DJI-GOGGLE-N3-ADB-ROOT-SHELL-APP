/*
 * n3app.h — minimal SDK for in-goggles N3 apps.
 *
 * An app is a preload mod loaded by n3mods.so. While
 * /data/local/tmp/n3_app_on exists, the framework draws a window into the live
 * 1920x1080 dmabuf, backs up the window area, and restores it on exit.
 * It never hooks or suppresses duss_hal_display_push_frame.
 *
 * Colors are 0xAARRGGBB (stored little-endian as BGRA, matching the N3).
 */
#ifndef N3APP_H
#define N3APP_H

#define N3_KEY_BACK  158
#define N3_KEY_ENTER 28

typedef unsigned int n3_color;
typedef struct {
    unsigned int *pixels;
    int w, h, stride;   /* stride is in pixels */
} n3_surface;

typedef struct n3_app {
    const char *name;
    int x, y, w, h;                 /* window rect; 0,0,0,0 = default */
    int manual_back;                /* 1 = app handles BACK; default hides */
    int right_select;               /* legacy: key 4 is UP on N3; keep 0 */
    void (*on_open)(n3_surface *s);
    void (*on_tick)(n3_surface *s, unsigned int frame);
    void (*on_key)(int key);
    void (*on_swipe)(int dx, int dy);   /* raw touchpad deltas */
    void (*on_tap)(int x, int y);       /* raw touchpad position */
    void (*on_close)(void);
} n3_app;

/* Drawing (all clipped to the surface). */
void n3_fill(n3_surface *s, int x, int y, int w, int h, n3_color c);
void n3_frame_rect(n3_surface *s, int x, int y, int w, int h, int t, n3_color c);
int  n3_text_width(const char *text, int scale);
void n3_text(n3_surface *s, int x, int y, const char *text, int scale, n3_color c);

/* Start the app. Call from natartos_mod_init with the loader's dlsym. */
int n3_start(const n3_app *app, void *(*loader_dlsym)(void *, const char *));

/* Close the app window and restore the UI. */
void n3_hide(void);

#endif /* N3APP_H */
