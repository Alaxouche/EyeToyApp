"""The AVI muxer: structure, sizes and index, read back byte by byte."""

import struct
import tempfile
import unittest
from pathlib import Path

from eyetoy.recorder import AviWriter


def fake_jpeg(n: int, size: int) -> bytes:
    body = bytes((n + i) % 251 for i in range(size))
    return b"\xff\xd8" + body + b"\xff\xd9"


def chunks(data: bytes, start: int, end: int):
    """Yield (fourcc, payload offset, size) for RIFF chunks in [start, end)."""
    pos = start
    while pos < end:
        fourcc, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        yield fourcc, pos + 8, size
        pos += 8 + size + (size & 1)


class AviWriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "clip.avi"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, frames):
        with AviWriter(self.path, 320, 240, 30) as writer:
            for frame in frames:
                writer.add(frame)
        return self.path.read_bytes()

    def test_structure_and_index(self):
        # Odd and even sizes, to exercise the word-alignment padding.
        frames = [fake_jpeg(i, 1000 + i) for i in range(5)]
        data = self.write(frames)

        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(struct.unpack_from("<I", data, 4)[0], len(data) - 8)
        self.assertEqual(data[8:12], b"AVI ")

        top = {fourcc: (off, size) for fourcc, off, size
               in chunks(data, 12, len(data))}
        self.assertIn(b"idx1", top)
        lists = [(data[off:off + 4], off, size)
                 for fourcc, off, size in chunks(data, 12, len(data))
                 if fourcc == b"LIST"]
        kinds = [kind for kind, _off, _size in lists]
        self.assertEqual(kinds, [b"hdrl", b"movi"])

        _kind, movi_off, movi_size = lists[1]
        movi = list(chunks(data, movi_off + 4, movi_off + movi_size))
        self.assertEqual(len(movi), len(frames))
        for (fourcc, off, size), frame in zip(movi, frames):
            self.assertEqual(fourcc, b"00dc")
            self.assertEqual(data[off:off + size], frame)

        idx_off, idx_size = top[b"idx1"]
        self.assertEqual(idx_size, 16 * len(frames))
        for i, frame in enumerate(frames):
            fourcc, flags, offset, size = struct.unpack_from(
                "<4sIII", data, idx_off + 16 * i)
            self.assertEqual(fourcc, b"00dc")
            self.assertEqual(size, len(frame))
            # Offsets count from the 'movi' FourCC.
            self.assertEqual(data[movi_off + offset:movi_off + offset + 4], b"00dc")

    def test_frame_count_in_headers(self):
        data = self.write([fake_jpeg(i, 500) for i in range(7)])
        avih = data.index(b"avih") + 8
        self.assertEqual(struct.unpack_from("<I", data, avih + 16)[0], 7)
        strh = data.index(b"strh") + 8
        self.assertEqual(data[strh:strh + 8], b"vidsMJPG")
        self.assertEqual(struct.unpack_from("<I", data, strh + 32)[0], 7)

    def test_close_releases_file_even_when_finishing_fails(self):
        writer = AviWriter(self.path, 320, 240, 30)
        writer.add(fake_jpeg(0, 100))

        def broken():
            raise OSError("disque plein")

        writer._finish = broken
        with self.assertRaises(OSError):
            writer.close()
        self.assertTrue(writer._f.closed)
        self.path.unlink()          # would fail on Windows if still open

    def test_add_after_close_is_refused(self):
        writer = AviWriter(self.path, 320, 240, 30)
        writer.close()
        with self.assertRaises(ValueError):
            writer.add(fake_jpeg(0, 10))


if __name__ == "__main__":
    unittest.main()
