"""Grab a few frames and decode them to PNG, to prove the image is real."""

import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PIL import Image, ImageStat

from eyetoy.camera import EyeToy

OUT = pathlib.Path(__file__).resolve().parents[1] / "captures"
OUT.mkdir(exist_ok=True)

frames = []
with EyeToy(320, 240, fps=30) as cam:
    cam.bring_up()
    cam.configure()
    cam.start(frames.append)
    cam.pump(2.5)          # let auto-exposure and white balance settle
    cam.stop()

print(f"captured {len(frames)} frames")

# Take a late frame: the first ones are exposed with the sensor defaults.
for label, frame in (("first", frames[0]), ("settled", frames[-1])):
    image = Image.open(io.BytesIO(frame))
    image.load()
    path = OUT / f"{label}.png"
    image.save(path)
    stat = ImageStat.Stat(image.convert("RGB"))
    means = ", ".join(f"{c:.0f}" for c in stat.mean)
    print(f"{label}: {image.size} {image.mode} -> {path.name}  "
          f"mean RGB=({means})  stddev={stat.stddev[0]:.1f}")
