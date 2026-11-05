"""Record a real AVI, then re-parse it from scratch to verify the container."""

import io
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PIL import Image

from eyetoy.camera import EyeToy
from eyetoy.recorder import AviWriter

OUT = pathlib.Path(__file__).resolve().parents[1] / "captures"
OUT.mkdir(exist_ok=True)
path = OUT / "test.avi"

with EyeToy(320, 240, fps=30) as cam:
    cam.bring_up()
    cam.configure()
    with AviWriter(path, 320, 240, 30) as avi:
        cam.start(avi.add)
        cam.pump(3.0)
        cam.stop()
        frames, measured = avi.frames, avi.close()

print(f"recorded {frames} frames -> {path.name} "
      f"({path.stat().st_size / 1024:.0f} KiB, {measured:.1f} fps)")

# --- independent re-parse -------------------------------------------------
data = path.read_bytes()
assert data[:4] == b"RIFF", "not a RIFF file"
assert data[8:12] == b"AVI ", "not an AVI"
assert len(data) == struct.unpack("<I", data[4:8])[0] + 8, "RIFF size mismatch"


def walk(buf, start, end, depth=0):
    """Yield (fourcc, payload_offset, size) for each chunk in a range."""
    pos = start
    while pos + 8 <= end:
        fourcc = buf[pos:pos + 4]
        size = struct.unpack("<I", buf[pos + 4:pos + 8])[0]
        yield fourcc, pos + 8, size, depth
        if fourcc == b"LIST":
            yield from walk(buf, pos + 12, pos + 8 + size, depth + 1)
        pos += 8 + size + (size & 1)


top = {}
for fourcc, offset, size, depth in walk(data, 12, len(data)):
    label = fourcc.decode("latin1")
    if fourcc == b"LIST":
        label += f"/{data[offset:offset + 4].decode('latin1')}"
    if fourcc != b"00dc":
        print(f"  {'  ' * depth}{label:12s} @{offset - 8:<9} {size} bytes")
    top.setdefault(label, (offset, size))

avih = top["avih"][0]
(micros, _max_bps, _pad, _flags, total_frames, _init, streams,
 _bufsize, width, height) = struct.unpack("<10I", data[avih:avih + 40])
print(f"\nheader says: {width}x{height}, {total_frames} frames, "
      f"{streams} stream, {1_000_000 / micros:.1f} fps")
assert total_frames == frames, f"dwTotalFrames {total_frames} != {frames}"
assert (width, height) == (320, 240), "wrong dimensions in header"

# --- follow idx1 and decode the frames it points at -----------------------
idx_off, idx_size = top["idx1"]
movi_off = top["LIST/movi"][0]          # payload starts at the 'movi' FourCC
entries = idx_size // 16
assert entries == frames, f"idx1 has {entries} entries, expected {frames}"

decoded = 0
for i in range(entries):
    ckid, flags, offset, size = struct.unpack(
        "<4sIII", data[idx_off + i * 16:idx_off + (i + 1) * 16])
    assert ckid == b"00dc", f"entry {i} has id {ckid!r}"
    chunk = movi_off + offset
    assert data[chunk:chunk + 4] == b"00dc", f"entry {i} points at garbage"
    assert struct.unpack("<I", data[chunk + 4:chunk + 8])[0] == size
    if i in (0, entries // 2, entries - 1):
        jpeg = data[chunk + 8:chunk + 8 + size]
        image = Image.open(io.BytesIO(jpeg))
        image.load()
        assert image.size == (320, 240), image.size
        decoded += 1

print(f"idx1: {entries} entries, all offsets valid, {decoded} frames decoded OK")
print("\nAVI container is well formed.")
