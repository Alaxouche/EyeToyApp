"""Optional virtual-camera output, so other apps can use the EyeToy.

This republishes decoded frames through pyvirtualcam, which needs a virtual
camera device already registered on the system. On Windows that means the OBS
Virtual Camera (installed with OBS Studio) or Unity Capture. Windows has no way
for an unsigned, unpackaged program to register one of its own, so the
dependency on OBS is not something the app can remove.

Everything here degrades gracefully: if the library or the device is missing,
:func:`availability` explains why and the feature simply stays off.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

import numpy as np
from PIL import Image

from .i18n import t

# How long to wait before trying a failed virtual device again.
RETRY_DELAY = 3.0

# The OBS Virtual Camera is the one virtual video device on Windows that is
# WHQL-signed, free, widely installed and installable unattended. OBS itself
# does not need to run: the installer registers the DirectShow filter, and
# pyvirtualcam feeds it directly through shared memory.
OBS_PACKAGE = "OBSProject.OBSStudio"

_NO_WINDOW = 0x08000000

_CAMERA_CLS = None
_IMPORT_ERROR: str | None = None

try:
    import pyvirtualcam
    _CAMERA_CLS = pyvirtualcam.Camera
except Exception as exc:                            # noqa: BLE001
    _IMPORT_ERROR = str(exc)


def availability() -> tuple[bool, str]:
    """Whether a virtual camera can be opened, and a message explaining it."""
    if _CAMERA_CLS is None:
        return False, t("vcam.library_missing", error=_IMPORT_ERROR)
    try:
        with _CAMERA_CLS(width=320, height=240, fps=30, print_fps=False) as cam:
            return True, t("vcam.device", device=cam.device)
    except Exception as exc:                        # noqa: BLE001
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return False, t("vcam.no_device", error=message)


def can_install() -> bool:
    """Whether winget is present to install the backend unattended."""
    try:
        return subprocess.run(["winget", "--version"], capture_output=True,
                              timeout=30, creationflags=_NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_backend(progress: Callable[[str], None] = lambda _m: None) -> bool:
    """Install OBS Studio through winget, for its virtual camera device.

    Returns whether a virtual camera is available afterwards. winget raises its
    own elevation prompt, so nothing here needs administrator rights.
    """
    if not can_install():
        progress(t("vcam.no_winget"))
        return False
    progress(t("vcam.installing"))
    try:
        result = subprocess.run(
            ["winget", "install", "--id", OBS_PACKAGE, "--exact", "--silent",
             "--accept-package-agreements", "--accept-source-agreements",
             "--disable-interactivity"],
            capture_output=True, text=True, timeout=1800,
            creationflags=_NO_WINDOW, encoding="utf-8", errors="replace")
    except subprocess.SubprocessError as exc:
        progress(t("vcam.install_failed", error=exc))
        return False
    if result.returncode != 0:
        tail = (result.stdout or result.stderr or "").strip().splitlines()
        progress(t("vcam.winget_failed",
                   error=tail[-1] if tail else result.returncode))
        return False
    progress(t("vcam.checking"))
    ok, message = availability()
    progress(message)
    return ok


class VirtualCamera:
    """Pushes frames to a system virtual camera, reopening it on mode changes."""

    def __init__(self) -> None:
        self._cam = None
        self._size: tuple[int, int] | None = None
        self._retry_after = 0.0
        self.device: str | None = None
        self.error: str | None = None

    @property
    def active(self) -> bool:
        return self._cam is not None

    def send(self, image: Image.Image, fps: float) -> None:
        """Publish one frame, opening or resizing the device as needed."""
        if _CAMERA_CLS is None:
            self.error = _IMPORT_ERROR
            return
        # After a failure, back off instead of retrying on every single frame:
        # reopening a missing device thirty times a second would stall the UI.
        if self._cam is None and time.monotonic() < self._retry_after:
            return
        size = (image.width, image.height)
        if self._cam is None or self._size != size:
            self.close()
            try:
                self._cam = _CAMERA_CLS(width=size[0], height=size[1],
                                        fps=max(1, round(fps)) or 30,
                                        print_fps=False)
                self._size = size
                self.device = self._cam.device
                self.error = None
            except Exception as exc:                # noqa: BLE001
                self._cam = None
                self.error = str(exc).splitlines()[0]
                self._retry_after = time.monotonic() + RETRY_DELAY
                return
        frame = np.asarray(image.convert("RGB"), dtype=np.uint8)
        try:
            self._cam.send(frame)
        except Exception as exc:                    # noqa: BLE001
            self.error = str(exc).splitlines()[0]
            self._retry_after = time.monotonic() + RETRY_DELAY
            self.close()

    def close(self) -> None:
        if self._cam is not None:
            try:
                self._cam.close()
            except Exception:                       # noqa: BLE001
                pass
        self._cam = None
        self._size = None
        self.device = None
