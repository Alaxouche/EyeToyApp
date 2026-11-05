"""Driver setup: automatic install, assisted fallback, and removal.

Binding a generic driver to a device needs an INF whose catalogue is signed by
a certificate Windows trusts. There is no way around that, so the catalogue is
generated, self-signed, and its certificate placed in the machine's trust store
at install time - which is exactly what Zadig does behind its own UAC prompt.

Three routes are offered:

* :func:`install_winusb` runs the bundled ``wdi-simple.exe``, built from libwdi
  for WinUSB only. One click, one elevation prompt, nothing else to do.
* :func:`install_with_zadig` downloads the official Zadig, verifies its
  Authenticode signature before running anything, and hands over to it. This is
  the way back to libusbK, or out of any situation the automatic path cannot
  handle.
* :func:`uninstall_driver` undoes the automatic route: it removes the generated
  driver package and the certificate it trusted.

Programs are started with ``ShellExecuteExW`` directly, never through a shell:
arguments are quoted with the same rules the C runtime uses to split them, so
paths with spaces or apostrophes reach the program intact, and the program's
real exit code comes back.

Either way nothing needs restarting: the camera session retries on its own and
picks the device up within a couple of seconds.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from . import paths
from .i18n import t

log = logging.getLogger(__name__)

# The camera the installer binds, and the interface carrying video. Interfaces
# 1 and 2 are the built-in microphone and must be left to the Windows audio
# stack, so only interface 0 is ever touched.
VENDOR_ID = 0x054C
PRODUCT_ID = 0x0155
VIDEO_INTERFACE = 0
DEVICE_NAME = "EyeToy USB camera"
INF_NAME = "eyetoy_winusb.inf"
WDI_WINUSB = 0

RELEASES_API = "https://api.github.com/repos/pbatard/libwdi/releases/latest"
# Compared with the certificate's CN exactly, not searched as a substring.
EXPECTED_SIGNER = "Akeo Consulting"
USER_AGENT = "EyeToyStudio"

# Where the downloaded helper and the extracted driver files are kept.
CACHE_DIR = paths.data_dir()

Progress = Callable[[str], None]

# libwdi return codes (libwdi.h), which wdi-simple passes on as its exit code.
# Their descriptions are the "wdi.<code>" entries of the translation catalogue.
WDI_ERROR_CODES = (-1, -2, -3, -4, -5, -6, -7, -9, -11, -12, -14, -15, -16,
                   -17, -18, -19)

# Keep spawned console helpers invisible: the app is built windowed, so a
# console window would flash in the user's face.
_NO_WINDOW = 0x08000000

ERROR_CANCELLED = 1223


class DriverSetupError(RuntimeError):
    pass


# -- process launching ------------------------------------------------------
class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_HIDE, SW_SHOWNORMAL = 0, 1
WAIT_TIMEOUT = 0x102


def _win32():
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return shell32, kernel32


def shell_execute(program: str | Path, arguments: list[str], *,
                  elevate: bool = False, directory: Path | None = None,
                  show: int = SW_HIDE, wait: bool = True,
                  timeout: float = 600.0) -> int | None:
    """Start ``program``, optionally elevated, and return its exit code.

    ``arguments`` is a list: it is quoted here, by the C runtime's rules. The
    exit code is returned signed, as a C ``int``. Returns None when ``wait`` is
    false. Raises DriverSetupError if the user dismisses the UAC prompt.
    """
    shell32, kernel32 = _win32()
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
    info.lpVerb = "runas" if elevate else "open"
    info.lpFile = str(program)
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory = str(directory) if directory else None
    info.nShow = show
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise DriverSetupError(t("setup.elevation_refused"))
        raise DriverSetupError(t("setup.launch_failed",
                                 error=ctypes.FormatError(error)))
    if not info.hProcess:
        return None
    try:
        if not wait:
            return None
        if kernel32.WaitForSingleObject(info.hProcess,
                                        int(timeout * 1000)) == WAIT_TIMEOUT:
            raise DriverSetupError(t("setup.timeout"))
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise DriverSetupError(t("setup.exit_code"))
        return ctypes.c_int32(code.value).value
    finally:
        kernel32.CloseHandle(info.hProcess)


def powershell_exe() -> str:
    """Windows PowerShell by full path, never whatever is first on PATH."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    path = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(path) if path.is_file() else "powershell.exe"


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted literal. PowerShell also treats the
    typographic single quotes as quote characters, so those are doubled too."""
    for quote in "'\u2018\u2019\u201a\u201b":
        text = text.replace(quote, quote * 2)
    return f"'{text}'"


def _encoded(script: str) -> list[str]:
    """powershell.exe arguments running ``script`` with no quoting at all."""
    return ["-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii")]


def _run(args: list[str], timeout: int = 900,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=_NO_WINDOW, encoding="utf-8",
                          errors="replace", env=env)


# -- manual route: Zadig ------------------------------------------------------
def _latest_zadig_url() -> tuple[str, str]:
    request = urllib.request.Request(
        RELEASES_API, headers={"User-Agent": USER_AGENT,
                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("zadig-") and name.endswith(".exe"):
            return asset["browser_download_url"], name
    raise DriverSetupError(t("setup.no_zadig"))


def verify_signature(path: Path) -> str:
    """Return the signer name, or raise if the file is not properly signed.

    The path travels in an environment variable, so no character in it can
    break out of the script.
    """
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:EYETOY_SIGNED; "
              "Write-Output $s.Status; "
              "Write-Output $s.SignerCertificate.GetNameInfo('SimpleName', $false)")
    env = dict(os.environ, EYETOY_SIGNED=str(path))
    result = _run([powershell_exe(), *_encoded(script)], timeout=120, env=env)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2 or lines[0] != "Valid":
        raise DriverSetupError(t("setup.bad_signature",
                                 status=lines[0] if lines else t("setup.unknown")))
    signer = lines[1]
    if signer != EXPECTED_SIGNER:
        raise DriverSetupError(t("setup.wrong_signer", signer=signer))
    return signer


def fetch_zadig(progress: Progress = lambda _m: None) -> Path:
    """Download Zadig if needed and return its path, signature checked."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    progress(t("setup.looking_up"))
    url, name = _latest_zadig_url()
    target = CACHE_DIR / name

    if not target.exists():
        progress(t("setup.downloading", name=name))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        partial = target.with_suffix(".part")
        with urllib.request.urlopen(request, timeout=120) as response, \
                partial.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(65536):
                out.write(chunk)
                done += len(chunk)
                if total:
                    progress(t("setup.download_progress",
                               percent=done * 100 // total))
        partial.replace(target)

    progress(t("setup.checking_signature"))
    try:
        signer = verify_signature(target)
    except DriverSetupError:
        # A corrupt or tampered download must not stick around in the cache.
        target.unlink(missing_ok=True)
        raise
    progress(t("setup.signature_ok", signer=signer))
    return target


def install_with_zadig(progress: Progress = lambda _m: None) -> None:
    """Fetch, verify and launch Zadig, for the manual route."""
    zadig = fetch_zadig(progress)
    progress(t("setup.launching_zadig"))
    shell_execute(zadig, [], elevate=True, directory=zadig.parent,
                  show=SW_SHOWNORMAL, wait=False)
    progress(t("setup.zadig_open"))


# -- automatic route ----------------------------------------------------------
def wdi_simple_path() -> Path | None:
    """Locate the bundled installer, frozen build or source tree."""
    candidate = paths.resource("vendor", "wdi-simple.exe")
    return candidate if candidate.is_file() else None


def wdi_arguments(extract_dir: Path, *, extract_only: bool = False) -> list[str]:
    arguments = ["-v", f"0x{VENDOR_ID:04X}", "-p", f"0x{PRODUCT_ID:04X}",
                 "-i", str(VIDEO_INTERFACE), "-t", str(WDI_WINUSB),
                 "-n", DEVICE_NAME, "-f", INF_NAME, "-d", str(extract_dir), "-s"]
    if extract_only:
        arguments.append("-x")
    return arguments


def extraction_dir() -> Path:
    """Where the installer writes the INF, catalogue and its helper.

    wdi-simple reads its command line in the ANSI code page, but libwdi treats
    paths as UTF-8: any non-ASCII character is mangled on the way. Measured
    with a "Jérôme" folder: exit code 0, and the files land in a sibling folder
    named "J?r?me", so the install that follows cannot find them. A Windows
    account name with an accent puts %LOCALAPPDATA% in exactly that case, so
    such paths are avoided in favour of %ProgramData%, which standard users
    may create folders in.
    """
    candidates = [CACHE_DIR / "driver",
                  Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                  / paths.APP_NAME / "driver"]
    for candidate in candidates:
        if str(candidate).isascii():
            return candidate
    raise DriverSetupError(t("setup.no_ascii_dir"))


def describe_wdi_error(code: int) -> str:
    if code in WDI_ERROR_CODES:
        return t(f"wdi.{code}")
    return t("setup.code", code=code)


def wait_for_camera(progress: Progress, seconds: int = 15) -> bool:
    from .ov519 import Status, probe
    detail = ""
    for _ in range(seconds):
        status, detail = probe()
        if status is Status.OK:
            progress(t("session.ready"))
            return True
        time.sleep(1.0)
    progress(detail)
    return False


def install_winusb(progress: Progress = lambda _m: None) -> bool:
    """Bind WinUSB to the camera's video interface. Returns whether it worked.

    Runs elevated: the catalogue can only be signed, and its certificate
    trusted, with administrator rights.
    """
    installer = wdi_simple_path()
    if installer is None:
        progress(t("setup.installer_missing"))
        return False

    progress(t("setup.installing"))
    try:
        extract = extraction_dir()
        extract.mkdir(parents=True, exist_ok=True)
        code = shell_execute(installer, wdi_arguments(extract), elevate=True,
                             directory=extract)
    except (DriverSetupError, OSError) as exc:
        log.warning("driver install: %s", exc)
        progress(t("setup.install_aborted", error=exc))
        return False
    if code != 0:
        log.error("wdi-simple failed: code %s", code)
        progress(t("setup.install_failed", error=describe_wdi_error(code)))
        return False

    # The driver stack needs a moment to settle before the device reappears.
    log.info("WinUSB driver installed")
    progress(t("setup.installed_checking"))
    return wait_for_camera(progress)


# -- removal ------------------------------------------------------------------
# Matches what the automatic route leaves behind and nothing else: driver
# packages generated by libwdi for the EyeToy's video interface, and the
# self-signed certificates libwdi created for them.
_HARDWARE_PATTERN = "VID_054C&PID_015[45]&MI_00"
_CERT_PATTERN = r"VID_054C&PID_015[45]&MI_00 \(libwdi autogenerated\)"


def uninstall_script(report: Path, *, dry_run: bool = False) -> str:
    """The PowerShell run elevated by :func:`uninstall_driver`.

    With ``dry_run`` it only lists what it would remove, which needs no rights.
    """
    act = "$false" if dry_run else "$true"
    return f"""
$ErrorActionPreference = 'Continue'
$act = {act}
$lines = New-Object System.Collections.Generic.List[string]
$infDir = Join-Path $env:SystemRoot 'INF'
$infs = Get-ChildItem -LiteralPath $infDir -Filter 'oem*.inf' | Where-Object {{
    (Select-String -LiteralPath $_.FullName -Pattern {ps_quote(_HARDWARE_PATTERN)} -Quiet) -and
    (Select-String -LiteralPath $_.FullName -Pattern 'libwdi' -SimpleMatch -Quiet)
}}
foreach ($inf in $infs) {{
    if ($act) {{
        & pnputil.exe /delete-driver $inf.Name /uninstall /force | Out-Null
        $lines.Add("driver $($inf.Name): code $LASTEXITCODE")
    }} else {{
        $lines.Add("driver $($inf.Name)")
    }}
}}
$certs = Get-ChildItem Cert:\\LocalMachine\\Root, Cert:\\LocalMachine\\TrustedPublisher |
    Where-Object {{ $_.Subject -match {ps_quote(_CERT_PATTERN)} }}
foreach ($cert in $certs) {{
    $store = $cert.PSParentPath.Split('\\')[-1]
    if ($act) {{ Remove-Item -LiteralPath $cert.PSPath }}
    $lines.Add("certificate $store $($cert.Thumbprint)")
}}
Set-Content -LiteralPath {ps_quote(str(report))} -Value $lines -Encoding UTF8
exit 0
"""


def uninstall_driver(progress: Progress = lambda _m: None) -> bool:
    """Remove the WinUSB binding and the certificate the install trusted."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    report = CACHE_DIR / "uninstall-report.txt"
    report.unlink(missing_ok=True)
    progress(t("setup.uninstalling"))
    try:
        code = shell_execute(powershell_exe(),
                             _encoded(uninstall_script(report)), elevate=True,
                             timeout=300)
    except DriverSetupError as exc:
        progress(t("setup.uninstall_aborted", error=exc))
        return False
    try:
        removed = [line.strip() for line in
                   report.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip()]
    except OSError:
        removed = []
    log.info("uninstall (code %s): %s", code, removed)
    if code != 0:
        progress(t("setup.uninstall_failed", code=code))
        return False
    if not removed:
        progress(t("setup.nothing_to_remove"))
        return True
    drivers = sum(line.startswith("driver ") for line in removed)
    certs = sum(line.startswith("certificate ") for line in removed)
    progress(t("setup.removed", drivers=drivers, certs=certs))
    return True
