"""Frame reassembly and alternate-setting choice, without any hardware."""

import unittest

from eyetoy.camera import EOF, SOF, EyeToy, order_alt_settings, trim_jpeg


def header(kind: int, empty: bool = False, button: bool = False) -> bytes:
    head = bytearray(16)
    head[0:3] = b"\xff\xff\xff"
    head[3] = kind
    head[9] = 1 if empty else 0
    head[11] = 1 if button else 0
    return bytes(head)


class ReassemblyTest(unittest.TestCase):
    def setUp(self):
        # The constructor only stores settings: no USB is touched until the
        # object is entered as a context manager.
        self.cam = EyeToy(320, 240, 30)
        self.frames = []
        self.cam._on_frame = self.frames.append

    def feed(self, *packets):
        for packet in packets:
            self.cam._on_packet(packet)

    def test_one_frame_across_packets(self):
        jpeg = b"\xff\xd8" + b"A" * 50 + b"\xff\xd9"
        self.feed(header(SOF) + jpeg[:20], jpeg[20:] + b"\x00" * 30,
                  header(EOF))
        self.assertEqual(self.frames, [jpeg])
        self.assertEqual(self.cam.stats["frames"], 1)

    def test_button_state_comes_from_eof(self):
        self.feed(header(SOF) + b"\xff\xd8\xff\xd9", header(EOF, button=True))
        self.assertTrue(self.cam.button)
        self.feed(header(SOF) + b"\xff\xd8\xff\xd9", header(EOF))
        self.assertFalse(self.cam.button)

    def test_empty_frame_is_discarded(self):
        self.feed(header(SOF) + b"\xff\xd8xx\xff\xd9", header(EOF, empty=True))
        self.assertEqual(self.frames, [])
        self.assertEqual(self.cam.stats["discarded"], 1)

    def test_frame_without_soi_is_discarded(self):
        self.feed(header(SOF) + b"\x00\x00", b"data", header(EOF))
        self.assertEqual(self.frames, [])

    def test_data_before_first_sof_is_ignored(self):
        self.feed(b"stray", header(EOF))
        self.assertEqual(self.frames, [])


class HelpersTest(unittest.TestCase):
    def test_trim_jpeg(self):
        self.assertEqual(trim_jpeg(b"\xff\xd8ab\xff\xd9\x00\x00"),
                         b"\xff\xd8ab\xff\xd9")
        self.assertEqual(trim_jpeg(b"no marker"), b"no marker")

    def test_alt_settings_largest_first_without_alt0(self):
        found = [(0, 0), (1, 384), (2, 512), (3, 768), (4, 896)]
        self.assertEqual(order_alt_settings(found),
                         [(4, 896), (3, 768), (2, 512), (1, 384)])

    def test_alt_settings_drops_zero_bandwidth(self):
        self.assertEqual(order_alt_settings([(1, 0), (2, 512)]), [(2, 512)])
        self.assertEqual(order_alt_settings([]), [])


if __name__ == "__main__":
    unittest.main()
