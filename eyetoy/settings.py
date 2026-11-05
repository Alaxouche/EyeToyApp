"""User settings persisted between runs, as a small JSON file.

Loading never fails: a missing, unreadable or hand-mangled file falls back to
the defaults key by key, so a bad value costs that one setting and nothing else.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import paths
from .i18n import LANGUAGES

log = logging.getLogger(__name__)

DEFAULTS: dict[str, object] = {
    "language": "en",
    "mode": "qvga30",
    "brightness": 128,
    "exposure": 127,
    "saturation": 128,
    "autogain": True,
    "mirror": True,
    "smooth": False,
    # Empty means the default: Pictures\EyeToy Studio.
    "captures_dir": "",
}

# The image settings "Restore default image settings" puts back.
IMAGE_KEYS = ("brightness", "exposure", "saturation", "autogain", "mirror",
              "smooth")

MODE_KEYS = ("qvga30", "qvga15", "vga")
# Early builds stored the mode by its on-screen label.
_LEGACY_MODES = {"320 x 240 - 30 fps": "qvga30", "320 x 240 - 15 fps": "qvga15",
                 "640 x 480 - max": "vga"}

_BYTE_KEYS = ("brightness", "exposure", "saturation")
_BOOL_KEYS = ("autogain", "mirror", "smooth")


def default_path() -> Path:
    return paths.data_dir() / "settings.json"


def _clean(raw: object) -> dict[str, object]:
    values = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return values
    for key in _BYTE_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values[key] = max(0, min(255, int(value)))
    for key in _BOOL_KEYS:
        if isinstance(raw.get(key), bool):
            values[key] = raw[key]
    mode = raw.get("mode")
    if isinstance(mode, str):
        mode = _LEGACY_MODES.get(mode, mode)
        if mode in MODE_KEYS:
            values["mode"] = mode
    language = raw.get("language")
    if isinstance(language, str) and language in LANGUAGES:
        values["language"] = language
    if isinstance(raw.get("captures_dir"), str):
        values["captures_dir"] = raw["captures_dir"]
    return values


def load(path: Path | None = None) -> dict[str, object]:
    path = path or default_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, ValueError) as exc:
        log.warning("settings unreadable (%s), using defaults", exc)
        return dict(DEFAULTS)
    return _clean(raw)


def save(values: dict[str, object], path: Path | None = None) -> None:
    path = path or default_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(_clean(values), indent=2), encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        log.warning("settings not saved: %s", exc)
