"""The translation catalogue: complete, consistent, and actually used."""

import pathlib
import re
import string
import unittest

from eyetoy import i18n
from eyetoy.i18n import STRINGS, t

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fields(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text)
            if name}


class CatalogueTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_every_entry_has_every_language(self):
        for key, entry in STRINGS.items():
            for code in i18n.LANGUAGES:
                with self.subTest(key=key, language=code):
                    self.assertTrue(entry.get(code), "missing translation")

    def test_placeholders_match_across_languages(self):
        for key, entry in STRINGS.items():
            with self.subTest(key=key):
                self.assertEqual(fields(entry["fr"]), fields(entry["en"]))

    def test_english_is_the_default(self):
        self.assertEqual(i18n.DEFAULT_LANGUAGE, "en")
        self.assertEqual(t("control.mirror"), "Mirror")

    def test_switch_and_fallback(self):
        i18n.set_language("fr")
        self.assertEqual(t("control.mirror"), "Miroir")
        self.assertEqual(t("toast.photo_saved", name="a.png"), "photo : a.png")
        i18n.set_language("xx")
        self.assertEqual(i18n.language(), "en")

    def test_every_key_used_in_code_exists(self):
        used = set()
        for path in [ROOT / "app.py", *(ROOT / "eyetoy").glob("*.py")]:
            source = path.read_text(encoding="utf-8")
            used |= set(re.findall(r'\bt\(\s*f?"([a-z_]+\.[a-z0-9_.{}-]+)"',
                                   source))
        dynamic = {key for key in used if "{" in key}
        for key in sorted(used - dynamic):
            with self.subTest(key=key):
                self.assertIn(key, STRINGS)
        # Keys built at run time: the stream modes, controls and libwdi codes.
        for prefix in ("mode.", "control.", "wdi."):
            self.assertTrue(any(k.startswith(prefix) for k in STRINGS))


if __name__ == "__main__":
    unittest.main()
