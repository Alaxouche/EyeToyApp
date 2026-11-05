"""Capture a few seconds of video and report what actually came off the wire."""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from eyetoy.camera import EyeToy

OUT = pathlib.Path(__file__).resolve().parents[1] / "captures"
OUT.mkdir(exist_ok=True)

frames = []

with EyeToy(320, 240, fps=30) as cam:
    print(f"sensor: {cam.bring_up()}")
    cam.configure()
    print("mode configured, starting stream...")

    t0 = time.monotonic()
    cam.start(frames.append)
    cam.pump(3.0)
    cam.stop()
    elapsed = time.monotonic() - t0

print(f"\n--- {elapsed:.1f}s of capture ---")
for key, value in cam.stats.items():
    print(f"  {key}: {value}")
print(f"  throughput: {cam.stats['bytes'] / elapsed / 1024:.0f} KiB/s")
print(f"  frame rate: {len(frames) / elapsed:.1f} fps")

if not frames:
    print("\nNo complete frames. Nothing to dump.")
    sys.exit(1)

sizes = [len(f) for f in frames]
print(f"  frame sizes: min={min(sizes)} max={max(sizes)} avg={sum(sizes)//len(sizes)}")

sample = frames[len(frames) // 2]
raw = OUT / "frame.bin"
raw.write_bytes(sample)
print(f"\nwrote {raw} ({len(sample)} bytes)")
print("first 48 bytes:", sample[:48].hex(" "))
print("last  16 bytes:", sample[-16:].hex(" "))

# Which JPEG marker segments are present? A missing DHT is the known quirk of
# this bridge: it ships the scan without standard Huffman tables.
markers, i = [], 0
while i < len(sample) - 1:
    if sample[i] == 0xFF and sample[i + 1] not in (0x00, 0xFF):
        marker = sample[i + 1]
        markers.append(f"{marker:02x}@{i}")
        if marker == 0xDA:  # start of scan; entropy data follows
            break
        if marker in (0xD8,) or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        i += 2 + int.from_bytes(sample[i + 2:i + 4], "big")
        continue
    i += 1
print("markers:", " ".join(markers))
