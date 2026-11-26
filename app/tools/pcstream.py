"""pcstream - send the Windows desktop to the goggles over RNDIS.

Frames are JPEG, length-prefixed. Pacing matters: the goggles decodes one
frame in ~120 ms at 1080p, so sending faster than it can consume just builds a
queue and turns low latency into seconds of lag.

Usage:
    py -3.12 app/tools/pcstream.py                 # 1280x720, 12 fps
    py -3.12 app/tools/pcstream.py --size 1920x1080 --fps 6
    py -3.12 app/tools/pcstream.py --seconds 60
"""
from __future__ import annotations

import argparse
import io
import socket
import sys
import time

from PIL import Image, ImageGrab

HOST = "192.168.60.2"
PORT = 5570


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--quality", type=int, default=65)
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl+C")
    args = ap.parse_args()

    w, h = (int(v) for v in args.size.lower().split("x"))
    interval = 1.0 / args.fps if args.fps > 0 else 0.0

    sock = socket.create_connection((args.host, args.port), timeout=8)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)

    t0 = time.time()
    frames = 0
    slow = 0
    try:
        while True:
            tick = time.time()
            if args.seconds and tick - t0 >= args.seconds:
                break

            im = ImageGrab.grab().convert("RGB")
            im.thumbnail((w, h), Image.BILINEAR)
            if im.size != (w, h):                      # letterbox, keep aspect
                canvas = Image.new("RGB", (w, h), (0, 0, 0))
                canvas.paste(im, ((w - im.size[0]) // 2, (h - im.size[1]) // 2))
                im = canvas

            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=args.quality)
            data = buf.getvalue()
            try:
                sock.sendall(len(data).to_bytes(4, "little") + data)
            except OSError as exc:
                print("send failed:", exc)
                break

            frames += 1
            spent = time.time() - tick
            if spent > interval:
                slow += 1
            else:
                time.sleep(interval - spent)

            if frames % 30 == 0:
                el = time.time() - t0
                print("%d frames  %.1f fps  %d slow  %.0f KB/frame"
                      % (frames, frames / el, slow, len(data) / 1024))
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    el = time.time() - t0
    print("done: %d frames in %.1f s (%.1f fps, %d over budget)"
          % (frames, el, frames / el if el else 0, slow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
