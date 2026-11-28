/*
 * n3_hw_tunnel.h — PC -> goggles 1080p60 hardware display tunnel.
 *
 * Reference constants and helpers for the proven path:
 *
 *   NVENC H.264/H.265 (Annex-B) over TCP 5572
 *     -> OMX.dji.video_decoder.avc.vc8000d or hevc.vc8000d
 *     -> OMX_SetupTunnel(decoder, 1, sink, 0)
 *     -> OMX.dji.iv_renderer.yuv.extra_blending
 *
 * The full implementation is mods/h264/h264live.c. Do not allocate the
 * decoder output or sink main buffers: the tunnel owns them.
 *
 * No libc / OMX includes on purpose, so this can be dropped into a
 * freestanding natartos mod.
 */
#ifndef N3_HW_TUNNEL_H
#define N3_HW_TUNNEL_H

/* components */
#define N3_TUNNEL_DEC_H264   "OMX.dji.video_decoder.avc.vc8000d"
#define N3_TUNNEL_DEC_H265   "OMX.dji.video_decoder.hevc.vc8000d"
#define N3_TUNNEL_DEC_FALLBACK "OMX.dji.video_decoder.avc.ffmpeg"
#define N3_TUNNEL_SINK       "OMX.dji.iv_renderer.yuv.extra_blending"

/* ports */
#define N3_TUNNEL_DEC_IN     0
#define N3_TUNNEL_DEC_OUT    1
#define N3_TUNNEL_SINK_MAIN  0
#define N3_TUNNEL_SINK_SUB   1

/* geometry / buffers */
#define N3_TUNNEL_W          1920
#define N3_TUNNEL_H          1080
#define N3_TUNNEL_IN_BUFS    16   /* the port sizes itself to 6 MB */
#define N3_TUNNEL_OUT_BUFS   7
#define N3_TUNNEL_SUB_W      640
#define N3_TUNNEL_SUB_H      360
#define N3_TUNNEL_STRIDE     2048 /* hardware output / sink stride */
#define N3_TUNNEL_FRAME_BYTES (2048L * 1080L * 3L / 2L) /* 3,317,760 */

/* vendor URL parameter: OMX_SetParameter(sink, 0x0100000D, &hdr) */
#define N3_TUNNEL_URL_INDEX  0x0100000Du
#define N3_TUNNEL_URL \
    "{\"config_file\":\"/etc/display_frame_rate_map.json\"," \
    "\"enable_aux_liveview\":false," \
    "\"sub_stream_h_offset\":144,\"sub_stream_v_offset\":64," \
    "\"sub_stream_width\":496,\"sub_stream_height\":280," \
    "\"notify_sub_stream_alive_status\":true}"

#define N3_TUNNEL_TCP_PORT   5572
#define N3_TUNNEL_MAX_AU     (1024 * 1024)

/* header: u32 nSize = strlen(url)+0x0d, u32 nVersion=1, url at +8 */
static inline unsigned int n3_tunnel_url_size(const char *url) {
    unsigned int n = 0;
    while (url[n]) n++;
    return n + 0x0du;
}

/*
 * The hardware decoder reports stride 1920 but the real buffer is 2048.
 * Trust nFilledLen: stride = nFilledLen / (height*3/2).
 */
static inline int n3_tunnel_stride(unsigned int filled, int h) {
    int d = h * 3 / 2;
    return d ? (int)(filled / (unsigned int)d) : 0;
}

/* The software avc.ffmpeg fallback emits I420 planar (despite format 21). */
static inline int n3_tunnel_is_planar(const char *name) {
    for (; *name; name++) {
        const char *a = name, *b = "ffmpeg";
        while (*a && *b && *a == *b) { a++; b++; }
        if (!*b) return 1;
    }
    return 0;
}

/*
 * Extract SPS/PPS (AVC) or VPS/SPS/PPS (HEVC) from an Annex-B AU.
 * Feed the result with OMX_BUFFERFLAG_CODECCONFIG before the IDR.
 * Returns bytes written to out (0 if the AU has no config NALs).
 */
static inline int n3_tunnel_build_config(const unsigned char *au, int len,
                                         unsigned char *out, int max,
                                         int hevc) {
    int n = 0;
    for (int i = 0; i + 3 < len; ) {
        int sc = -1, sl = 0;
        if (au[i] == 0 && au[i + 1] == 0 && au[i + 2] == 1) { sc = i; sl = 3; }
        else if (au[i] == 0 && au[i + 1] == 0 && au[i + 2] == 0 &&
                 au[i + 3] == 1) { sc = i; sl = 4; }
        if (sc < 0) { i++; continue; }
        int j = sc + sl;
        int next = len;
        for (int k = j; k + 2 < len; k++) {
            if (au[k] == 0 && au[k + 1] == 0 && au[k + 2] == 1) { next = k; break; }
            if (k + 3 < len && au[k] == 0 && au[k + 1] == 0 &&
                au[k + 2] == 0 && au[k + 3] == 1) { next = k; break; }
        }
        int type = hevc ? ((au[j] >> 1) & 0x3F) : (au[j] & 0x1F);
        int want = hevc ? (type == 32 || type == 33 || type == 34)
                        : (type == 6 || type == 7 || type == 8);
        if (want) {
            int nl = next - sc;
            if (n + nl <= max) {
                for (int q = 0; q < nl; q++) out[n + q] = au[sc + q];
                n += nl;
            }
        }
        i = next;
    }
    return n;
}

/*
 * Host side: every TCP message is u32le length + one Annex-B access unit.
 * NVENC: preset p1, tune ull, bf 0, delay 0, CBR 30 Mbps, aud 1,
 * repeat_headers 1. Draw the Windows cursor before BGRA -> yuv420p.
 */

#endif /* N3_HW_TUNNEL_H */
