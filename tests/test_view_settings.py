"""Zoom geometry and settings persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from eyetoy import settings
from eyetoy.view import MAX_ZOOM, crop_box


class CropBoxTest(unittest.TestCase):
    def test_no_crop_at_unit_zoom(self):
        self.assertIsNone(crop_box(320, 240, 1.0, (0.5, 0.5)))

    def test_box_stays_inside_frame_at_every_extreme(self):
        for width, height in ((320, 240), (640, 480)):
            for zoom in (1.01, 1.5, 3.0, MAX_ZOOM):
                for center in ((0.5, 0.5), (0, 0), (1, 1), (0, 1), (1, 0)):
                    left, top, right, bottom = crop_box(width, height, zoom,
                                                        center)
                    self.assertTrue(0 <= left < right <= width)
                    self.assertTrue(0 <= top < bottom <= height)

    def test_box_keeps_aspect_ratio(self):
        left, top, right, bottom = crop_box(640, 480, 2.0, (0.5, 0.5))
        self.assertAlmostEqual((right - left) / (bottom - top), 4 / 3, places=2)
        self.assertEqual((right - left, bottom - top), (320, 240))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_defaults(self):
        self.assertEqual(settings.load(self.path), settings.DEFAULTS)

    def test_defaults_are_english_and_qvga(self):
        self.assertEqual(settings.DEFAULTS["language"], "en")
        self.assertEqual(settings.DEFAULTS["mode"], "qvga30")

    def test_round_trip(self):
        values = dict(settings.DEFAULTS, brightness=10, mirror=False,
                      mode="vga", language="fr", captures_dir=r"D:\Photos")
        settings.save(values, self.path)
        self.assertEqual(settings.load(self.path), values)

    def test_legacy_mode_label_is_migrated(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"mode": "640 x 480 - max"}),
                             encoding="utf-8")
        self.assertEqual(settings.load(self.path)["mode"], "vga")

    def test_unknown_language_and_mode_fall_back(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"language": "de", "mode": "4k"}),
                             encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual(loaded["language"], "en")
        self.assertEqual(loaded["mode"], "qvga30")

    def test_corrupt_file_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.DEFAULTS)

    def test_bad_values_fall_back_one_by_one(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "brightness": 999, "exposure": -4, "saturation": "x",
            "autogain": "yes", "mirror": False, "mode": [3],
            "language": ["fr"], "captures_dir": 7}), encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual(loaded["brightness"], 255)
        self.assertEqual(loaded["exposure"], 0)
        self.assertEqual(loaded["saturation"], settings.DEFAULTS["saturation"])
        self.assertEqual(loaded["autogain"], settings.DEFAULTS["autogain"])
        self.assertFalse(loaded["mirror"])
        self.assertEqual(loaded["mode"], settings.DEFAULTS["mode"])
        self.assertEqual(loaded["language"], "en")
        self.assertEqual(loaded["captures_dir"], "")


if __name__ == "__main__":
    unittest.main()
