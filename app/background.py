"""background.py - custom normal + idle backgrounds for the DJI Goggles N3.

The stock UI opens three 1920x1080 backgrounds and three 2304x1080 "idle"
screen-protector images.  We install:
  /vendor/background.jpg       1920x1080, optional logo overlay
  /vendor/background_idle.jpg  2304x1080, just the background (no logo)
The n3bg.so hook redirects the normal suffixes to the first and the idle
suffixes to the second, so the burn-in pan has extra width and never reveals
the stock UI behind it.
"""
from __future__ import annotations

import os

import n3ctl

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP_DIR, "assets")
BUILD = os.path.join(APP_DIR, "state", "build")
HOOK = os.path.join(ASSETS, "n3bg.so")

REF_SIZE = (1920, 1080)
IDLE_SIZE = (2304, 1080)
LOGO_SIZE = 340


def _base_image(src: str):
    from PIL import Image, ImageOps

    im = Image.open(src)
    im = ImageOps.exif_transpose(im).convert("RGB")
    return ImageOps.fit(im, REF_SIZE, Image.LANCZOS)


def _extended_idle(base):
    """2304x1080 background-only frame with mirrored side strips."""
    from PIL import Image

    idle = Image.new("RGB", IDLE_SIZE)
    side = (IDLE_SIZE[0] - REF_SIZE[0]) // 2
    idle.paste(base, (side, 0))
    left = base.crop((0, 0, side, REF_SIZE[1])).transpose(
        Image.FLIP_LEFT_RIGHT)
    right = base.crop((REF_SIZE[0] - side, 0, REF_SIZE[0], REF_SIZE[1])) \
        .transpose(Image.FLIP_LEFT_RIGHT)
    idle.paste(left, (0, 0))
    idle.paste(right, (side + REF_SIZE[0], 0))
    return idle


def _overlay_logo(base, logo_path):
    from PIL import Image, ImageFilter

    if not logo_path or not os.path.exists(logo_path):
        return base
    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    if logo.getchannel("A").getextrema() == (255, 255):
        # opaque logo on black: treat near-black as transparent
        mask = logo.convert("L").point(
            lambda v: 0 if v < 18 else min(255, int((v - 18) * 1.45)))
        mask = mask.filter(ImageFilter.GaussianBlur(0.6))
    else:
        mask = logo.getchannel("A")
    out = base.copy()
    x = (out.width - logo.width) // 2
    y = (out.height - logo.height) // 2 + 20
    out.paste(logo, (x, y), mask)
    return out


def prepare_images(src: str, logo: str | None = None):
    """Create (normal-with-logo, idle-background-only) in state/build."""
    os.makedirs(BUILD, exist_ok=True)
    base = _base_image(src)
    regular = _overlay_logo(base, logo)
    idle = _extended_idle(base)
    regular_path = os.path.join(BUILD, "background.jpg")
    idle_path = os.path.join(BUILD, "background_idle.jpg")
    regular.save(regular_path, "JPEG", quality=93, optimize=True)
    idle.save(idle_path, "JPEG", quality=93, optimize=True)
    return regular_path, idle_path


def preview_image(src: str, logo: str | None = None):
    """Return a 16:9 PIL preview of the normal (logo) image."""
    base = _overlay_logo(_base_image(src), logo)
    return base.resize((520, 293))


def install(src: str, logo: str | None = None, log=print, mods=None) -> bool:
    if not os.path.exists(HOOK):
        raise RuntimeError("missing background hook: " + HOOK)
    regular, idle = prepare_images(src, logo)
    log("Prepared normal background: %s (%d bytes)" %
        (os.path.basename(regular), os.path.getsize(regular)))
    log("Prepared idle background:   %s (%d bytes, %dx%d, no logo)" %
        (os.path.basename(idle), os.path.getsize(idle), IDLE_SIZE[0],
         IDLE_SIZE[1]))
    try:
        with n3ctl.vendor_write(log):
            # n3bg.so is mapped by the running UI; stop it before replacing.
            n3ctl.run_root(n3ctl.STOP_UI, timeout=15, retries=1)
            n3ctl.push_file(HOOK, n3ctl.BG_HOOK, log=log)
            n3ctl.push_file(regular, n3ctl.BG_IMAGE, log=log)
            n3ctl.push_file(idle, n3ctl.BG_IMAGE_IDLE, log=log)
            n3ctl.run_root("chmod 644 %s %s %s" %
                           (n3ctl.BG_HOOK, n3ctl.BG_IMAGE,
                            n3ctl.BG_IMAGE_IDLE), timeout=6, retries=1)
    except Exception:
        n3ctl.start_ui(log, mods=mods)
        raise
    return n3ctl.start_ui(log, mods=mods)


def remove(log=print, mods=None) -> bool:
    try:
        with n3ctl.vendor_write(log):
            n3ctl.run_root(n3ctl.STOP_UI, timeout=15, retries=1)
            n3ctl.run_root("rm -f %s %s %s" %
                           (n3ctl.BG_HOOK, n3ctl.BG_IMAGE,
                            n3ctl.BG_IMAGE_IDLE), timeout=8, retries=1)
            log("Removed the custom background hook and images.")
    except Exception:
        n3ctl.start_ui(log, mods=mods)
        raise
    return n3ctl.start_ui(log, mods=mods)


def status() -> dict:
    st = n3ctl.ui_state()
    return {
        "installed": bool(st.get("background")),
        "hook": st.get("background"),
    }
