"""Minimal MJPEG AVI muxer.

The bridge already hands us JPEG frames, so recording is a container problem
rather than a codec problem: the frames go into an AVI verbatim, with no
re-encoding, no quality loss and no external dependency.

Layout written here:

    RIFF....AVI
      LIST....hdrl
        avih....           main header
        LIST....strl
          strh....         stream header
          strf....         BITMAPINFOHEADER, biCompression = MJPG
      LIST....movi
        00dc.... <jpeg>    one chunk per frame, padded to an even length
      idx1....             one 16-byte entry per frame

Sizes and frame counts are only known at the end, so they are written as
placeholders and patched in :meth:`close`.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

AVIF_HASINDEX = 0x10
AVIIF_KEYFRAME = 0x10


class AviWriter:
    """Streams JPEG frames into an MJPEG AVI file."""

    def __init__(self, path: str | Path, width: int, height: int,
                 fps: float = 30.0):
        self.path = Path(path)
        self.width, self.height = width, height
        self.nominal_fps = fps
        self.frames = 0
        self.bytes_written = 0
        self._index: list[tuple[int, int]] = []   # (offset from movi, size)
        self._largest = 0
        self._started = time.monotonic()
        self._closed = False

        self._f = self.path.open("wb")
        try:
            self._write_headers()
        except BaseException:
            self._f.close()
            raise

    # -- public API ---------------------------------------------------------
    def add(self, jpeg: bytes) -> None:
        if self._closed:
            raise ValueError("recorder is closed")
        size = len(jpeg)
        self._largest = max(self._largest, size)
        offset = self._f.tell() - self._movi_start
        self._f.write(b"00dc" + struct.pack("<I", size))
        self._f.write(jpeg)
        if size & 1:                       # RIFF chunks are word aligned
            self._f.write(b"\x00")
        self._index.append((offset, size))
        self.frames += 1
        self.bytes_written += size

    def close(self) -> float:
        """Finish the file and return the measured frame rate."""
        if self._closed:
            return self.nominal_fps
        self._closed = True
        try:
            return self._finish()
        finally:
            # Even when finishing fails (a full disk, typically), the handle is
            # released so the partial file can at least be deleted or salvaged.
            self._f.close()

    def _finish(self) -> float:
        elapsed = time.monotonic() - self._started
        # Use the rate actually achieved, otherwise playback drifts: the bus
        # gives about 29.7 fps in QVGA and 14.4 in VGA, never the nominal value.
        fps = (self.frames / elapsed) if elapsed > 0 and self.frames else self.nominal_fps

        movi_end = self._f.tell()
        self._write_index()
        file_end = self._f.tell()

        self._patch("<I", 4, file_end - 8)                     # RIFF size
        self._patch("<I", self._movi_size_pos, movi_end - self._movi_start)
        self._patch("<I", self._avih + 0, round(1_000_000 / fps))
        self._patch("<I", self._avih + 4, round(self.bytes_written / elapsed)
                    if elapsed > 0 else 0)
        self._patch("<I", self._avih + 16, self.frames)        # dwTotalFrames
        self._patch("<I", self._avih + 28, self._largest)      # suggested buf
        self._patch("<I", self._strh + 20, 1000)               # dwScale
        self._patch("<I", self._strh + 24, round(fps * 1000))  # dwRate
        self._patch("<I", self._strh + 32, self.frames)        # dwLength
        self._patch("<I", self._strh + 36, self._largest)
        return fps

    def __enter__(self) -> "AviWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- internals ----------------------------------------------------------
    def _patch(self, fmt: str, offset: int, value: int) -> None:
        self._f.seek(offset)
        self._f.write(struct.pack(fmt, value))
        self._f.seek(0, 2)

    def _write_headers(self) -> None:
        f = self._f
        f.write(b"RIFF" + struct.pack("<I", 0) + b"AVI ")

        # strl holds its own FourCC plus the strh and strf chunks; hdrl holds
        # its FourCC, the avih chunk, and the whole strl list including header.
        strl_payload = 4 + (8 + 56) + (8 + 40)
        hdrl_payload = 4 + (8 + 56) + (8 + strl_payload)
        f.write(b"LIST" + struct.pack("<I", hdrl_payload) + b"hdrl")

        f.write(b"avih" + struct.pack("<I", 56))
        self._avih = f.tell()
        f.write(struct.pack(
            "<IIIIIIIIII",
            round(1_000_000 / self.nominal_fps),  # dwMicroSecPerFrame
            0,                                    # dwMaxBytesPerSec
            0,                                    # dwPaddingGranularity
            AVIF_HASINDEX,                        # dwFlags
            0,                                    # dwTotalFrames
            0,                                    # dwInitialFrames
            1,                                    # dwStreams
            0,                                    # dwSuggestedBufferSize
            self.width,
            self.height))
        f.write(b"\x00" * 16)                     # dwReserved[4]

        f.write(b"LIST" + struct.pack("<I", strl_payload) + b"strl")

        f.write(b"strh" + struct.pack("<I", 56))
        self._strh = f.tell()
        f.write(b"vids" + b"MJPG")
        f.write(struct.pack("<IHHIIIIIIII",
                            0,      # dwFlags
                            0, 0,   # wPriority, wLanguage
                            0,      # dwInitialFrames
                            1000,   # dwScale
                            round(self.nominal_fps * 1000),  # dwRate
                            0,      # dwStart
                            0,      # dwLength
                            0,      # dwSuggestedBufferSize
                            0xFFFFFFFF,  # dwQuality (default)
                            0))     # dwSampleSize
        f.write(struct.pack("<hhhh", 0, 0, self.width, self.height))

        f.write(b"strf" + struct.pack("<I", 40))
        f.write(struct.pack("<IiiHH", 40, self.width, self.height, 1, 24))
        f.write(b"MJPG")
        f.write(struct.pack("<IiiII", self.width * self.height * 3,
                            0, 0, 0, 0))

        f.write(b"LIST")
        self._movi_size_pos = f.tell()
        f.write(struct.pack("<I", 0))
        # Index offsets are measured from the 'movi' FourCC itself.
        self._movi_start = f.tell()
        f.write(b"movi")

    def _write_index(self) -> None:
        self._f.write(b"idx1" + struct.pack("<I", 16 * len(self._index)))
        for offset, size in self._index:
            self._f.write(b"00dc")
            self._f.write(struct.pack("<III", AVIIF_KEYFRAME, offset, size))
