"""Where the application reads and writes on disk.

Nothing is written next to the executable: it may live in Program Files, or any
other folder the user cannot write to. Captures go to the user's Pictures
folder, like the Windows Camera app does, and everything else to
%LOCALAPPDATA%\\EyeToyStudio.
"""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

APP_NAME = "EyeToyStudio"
CAPTURES_NAME = "EyeToy Studio"

# Known folder IDs from KnownFolders.h. Asking the shell rather than guessing
# Path.home() / "Pictures" follows a folder the user moved, or one OneDrive
# redirected.
FOLDERID_PICTURES = "33E28130-4E1E-4676-835A-98395C3BC3BB"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def known_folder(folder_id: str) -> Path | None:
    """Resolve a shell known folder, or None if the shell cannot."""
    if sys.platform != "win32":
        return None
    guid = _GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    out = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    try:
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                        ctypes.byref(out)) != 0:
            return None
        return Path(out.value) if out.value else None
    finally:
        ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))


def data_dir() -> Path:
    """Per-user folder for settings, logs and downloaded helpers."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME


def captures_dir(chosen: str = "") -> Path:
    """Folder for photos and videos.

    EYETOY_CAPTURES wins, then the folder the user chose in the settings, then
    "EyeToy Studio" in the user's Pictures folder.
    """
    override = os.environ.get("EYETOY_CAPTURES") or chosen
    if override:
        return Path(override)
    pictures = known_folder(FOLDERID_PICTURES) or Path.home() / "Pictures"
    return pictures / CAPTURES_NAME


def resource(*parts: str) -> Path:
    """A file shipped with the app, in a frozen build or the source tree."""
    root = getattr(sys, "_MEIPASS", None)
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)
