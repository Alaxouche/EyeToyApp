"""Draw the application icon: an EyeToy-style camera on its stand.

An original drawing, inspired by the camera's silhouette - dark rounded body,
oversized ringed lens, activity LED, swivel foot - with no logo or artwork
taken from the product. Rendered at 1024 px, then reduced per icon size so the
small sizes stay crisp instead of being one blurred thumbnail.

    .venv\\Scripts\\python.exe tools\\make_icon.py [preview.png]
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MASTER = 1024
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    width, height = size
    column = Image.new("RGBA", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t)
                                      for a, b in zip(top, bottom)))
    return column.resize(size)


def radial_gradient(diameter: int, inner: tuple, outer: tuple,
                    focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """A disc shaded from ``inner`` at the focus point to ``outer`` at the rim."""
    mask = Image.radial_gradient("L").resize((diameter * 2, diameter * 2))
    fx, fy = focus
    left = round(diameter * (1 - fx))
    top = round(diameter * (1 - fy))
    mask = mask.crop((left, top, left + diameter, top + diameter))
    return Image.composite(Image.new("RGBA", (diameter, diameter), outer),
                           Image.new("RGBA", (diameter, diameter), inner), mask)


def paste_shape(canvas: Image.Image, fill: Image.Image, mask: Image.Image,
                box: tuple[int, int]) -> None:
    layer = Image.new("RGBA", canvas.size)
    layer.paste(fill, box)
    shape = Image.new("L", canvas.size)
    shape.paste(mask, box)
    canvas.alpha_composite(Image.composite(layer, Image.new("RGBA", canvas.size),
                                           shape))


def disc_mask(diameter: int) -> Image.Image:
    mask = Image.new("L", (diameter, diameter))
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    return mask


def ring(canvas: Image.Image, center: tuple[int, int], diameter: int,
         fill: Image.Image) -> None:
    cx, cy = center
    paste_shape(canvas, fill, disc_mask(diameter),
                (cx - diameter // 2, cy - diameter // 2))


def draw_master() -> Image.Image:
    s = MASTER
    img = Image.new("RGBA", (s, s))

    # Soft contact shadow under the foot.
    shadow = Image.new("L", (s, s))
    ImageDraw.Draw(shadow).ellipse((200, 900, 824, 980), fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    img.alpha_composite(Image.merge("RGBA", (shadow.point(lambda _v: 0),) * 3
                                    + (shadow,)))

    # Foot and neck: a flat oval base with a short pillar up to the swivel.
    foot = (230, 820, 794, 940)
    paste_shape(img, vertical_gradient((foot[2] - foot[0], foot[3] - foot[1]),
                                       (92, 96, 106, 255), (28, 30, 36, 255)),
                _rounded_mask(foot, 60), foot[:2])
    neck = (440, 700, 584, 850)
    paste_shape(img, vertical_gradient((neck[2] - neck[0], neck[3] - neck[1]),
                                       (70, 74, 84, 255), (36, 38, 45, 255)),
                _rounded_mask(neck, 30), neck[:2])

    # Body: a wide rounded block, silver rim around a graphite face.
    body = (70, 150, 954, 760)
    paste_shape(img, vertical_gradient((body[2] - body[0], body[3] - body[1]),
                                       (214, 219, 228, 255), (118, 124, 136, 255)),
                _rounded_mask(body, 230), body[:2])
    face = (100, 180, 924, 730)
    paste_shape(img, vertical_gradient((face[2] - face[0], face[3] - face[1]),
                                       (58, 62, 72, 255), (20, 21, 26, 255)),
                _rounded_mask(face, 205), face[:2])

    # Lens: brushed outer ring, black barrel, tinted glass, then highlights.
    center = (512, 452)
    ring(img, center, 560, radial_gradient(560, (238, 241, 247, 255),
                                           (126, 132, 146, 255), (0.35, 0.3)))
    ring(img, center, 500, radial_gradient(500, (60, 64, 74, 255),
                                           (14, 15, 19, 255), (0.5, 0.35)))
    ring(img, center, 430, radial_gradient(430, (12, 12, 16, 255),
                                           (36, 38, 46, 255), (0.5, 0.5)))
    ring(img, center, 330, radial_gradient(330, (64, 132, 222, 255),
                                           (10, 22, 58, 255), (0.42, 0.38)))
    ring(img, center, 150, radial_gradient(150, (20, 38, 86, 255),
                                           (4, 8, 22, 255), (0.5, 0.5)))

    # Specular crescent on the glass, the cue that reads as "lens" at 16 px.
    glare = Image.new("L", (s, s))
    draw = ImageDraw.Draw(glare)
    draw.ellipse((395, 325, 585, 515), fill=235)
    draw.ellipse((430, 360, 640, 570), fill=0)
    glare = glare.filter(ImageFilter.GaussianBlur(6))
    img.alpha_composite(Image.merge(
        "RGBA", (Image.new("L", (s, s), 255),) * 3 + (glare,)))
    dot = Image.new("L", (s, s))
    ImageDraw.Draw(dot).ellipse((560, 500, 598, 538), fill=150)
    img.alpha_composite(Image.merge(
        "RGBA", (Image.new("L", (s, s), 255),) * 3
        + (dot.filter(ImageFilter.GaussianBlur(4)),)))

    # Activity LED, upper left of the face, with a faint glow.
    glow = Image.new("L", (s, s))
    ImageDraw.Draw(glow).ellipse((158, 248, 250, 340), fill=170)
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(Image.merge("RGBA", (
        Image.new("L", (s, s), 70), Image.new("L", (s, s), 170),
        Image.new("L", (s, s), 255), glow)))
    ImageDraw.Draw(img).ellipse((182, 272, 226, 316), fill=(150, 215, 255, 255))

    # Microphone grille, upper right: three short slots.
    draw = ImageDraw.Draw(img)
    for i in range(3):
        y = 262 + i * 30
        draw.rounded_rectangle((770, y, 860, y + 14), radius=7,
                               fill=(10, 11, 14, 255))
    return img


def _rounded_mask(box: tuple[int, int, int, int], radius: int) -> Image.Image:
    width, height = box[2] - box[0], box[3] - box[1]
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1),
                                           radius=radius, fill=255)
    return mask


def reduce(master: Image.Image, size: int) -> Image.Image:
    small = master.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 48:
        # Downscaling softens edges; a light unsharp mask restores the outline
        # without halos, on the colour channels only.
        rgb = small.convert("RGB").filter(
            ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2))
        small = Image.merge("RGBA", (*rgb.split(), small.getchannel("A")))
    return small


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    master = draw_master()
    master.save(ASSETS / "eyetoy.png")
    frames = [reduce(master, size) for size in ICO_SIZES]
    frames[-1].save(ASSETS / "eyetoy.ico",
                    sizes=[(n, n) for n in ICO_SIZES],
                    append_images=frames[:-1])
    if len(sys.argv) > 1:
        # Optional: every size side by side on a dark background, to check the
        # small ones by eye.
        strip = Image.new("RGBA", (sum(ICO_SIZES) + 10 * len(ICO_SIZES), 256),
                          (40, 42, 48, 255))
        x = 0
        for frame in frames:
            strip.alpha_composite(frame, (x, 256 - frame.height))
            x += frame.width + 10
        strip.save(sys.argv[1])
    print(f"wrote {ASSETS / 'eyetoy.ico'} ({', '.join(map(str, ICO_SIZES))})")


if __name__ == "__main__":
    main()
