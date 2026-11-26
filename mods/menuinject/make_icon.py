"""Draw the E420Z hex logo as a 96x96 RGBA icon and emit a C header."""
import math
import os

from PIL import Image, ImageDraw

S = 4          # supersample
W = 64
C = W * S

img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
cx = cy = C / 2


def hexpts(r, rot=0):
    pts = []
    for i in range(6):
        a = math.radians(60 * i + rot)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# glow / outer ring
d.polygon(hexpts(0.46 * C), outline=(180, 70, 255, 255), width=int(0.055 * C))
# inner body
d.polygon(hexpts(0.36 * C), fill=(106, 31, 176, 255),
          outline=(220, 160, 255, 255), width=int(0.025 * C))
# second ring
d.polygon(hexpts(0.24 * C), outline=(200, 120, 255, 255), width=int(0.018 * C))
# white center disc and dark pupil
rr = 0.085 * C
d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 255, 255, 255))
rr2 = 0.045 * C
d.ellipse((cx - rr2, cy - rr2, cx + rr2, cy + rr2), fill=(20, 8, 36, 255))
rr3 = 0.016 * C
d.ellipse((cx - rr3, cy - rr3, cx + rr3, cy + rr3), fill=(255, 255, 255, 255))

img = img.resize((W, W), Image.LANCZOS)
img.save(os.path.join(os.path.dirname(__file__), "icon.png"))

data = img.tobytes()  # RGBA
lines = ["/* auto-generated E420Z icon: 96x96 RGBA */",
         "#define E420Z_ICON_W 64", "#define E420Z_ICON_H 64",
         "static const unsigned char E420Z_ICON[%d] = {" % len(data)]
for i in range(0, len(data), 16):
    lines.append("  " + ",".join("0x%02x" % b for b in data[i:i + 16]) + ",")
lines.append("};")
open(os.path.join(os.path.dirname(__file__), "icon.h"), "w",
     encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote icon.png and icon.h", W, W, len(data))
