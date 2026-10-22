# Regenerate: uv run python mac/Resources/make-icon.py mac/Resources/AppIcon.png
# Mac app icon: the web OS mark (light ring, blue dot on navy) on the macOS rounded-square grid.
import sys
from PIL import Image, ImageDraw, ImageFilter

S = 4  # supersampling
N = 1024 * S
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))

# macOS grid: 824 px body centred in 1024, corner radius ~185, soft drop shadow
inset, size, radius = 100 * S, 824 * S, 185 * S
shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    (inset, inset + 12 * S, inset + size, inset + size + 12 * S), radius, fill=(0, 0, 0, 110))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14 * S)))

# body: navy with a gentle top-to-bottom gradient
top, bottom = (0x2a, 0x32, 0x45), (0x17, 0x1c, 0x27)
grad = Image.new("RGBA", (N, N))
gd = ImageDraw.Draw(grad)
for y in range(inset, inset + size):
    t = (y - inset) / size
    gd.line([(0, y), (N, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((inset, inset, inset + size, inset + size), radius, fill=255)
img.paste(grad, (0, 0), mask)

# the mark, scaled from the 512 web icon (ring r 143 / width 35, dot r 51) to the 824 body
c = N // 2
k = 824 / 512 * 0.92 * S
d = ImageDraw.Draw(img)
ring_r, ring_w, dot_r = 143 * k, 35 * k, 51 * k
d.ellipse((c - ring_r, c - ring_r, c + ring_r, c + ring_r), outline=(0xe7, 0xec, 0xf7, 255), width=round(ring_w))
d.ellipse((c - dot_r, c - dot_r, c + dot_r, c + dot_r), fill=(0x6b, 0x8f, 0xf0, 255))

img.resize((1024, 1024), Image.LANCZOS).save(sys.argv[1])
