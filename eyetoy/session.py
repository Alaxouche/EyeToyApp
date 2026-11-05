"""A background camera session that owns every USB call.

libusb handles are used from one thread only: this one. The GUI reads the most
recent frame through :meth:`latest` and pushes control changes through a
coalescing map, so no USB call is ever made from the Tk event loop.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path

from .camera import EyeToy
from .i18n import t
from .ov519 import EyeToyError, Status, probe
from .recorder import AviWriter

log = logging.getLogger(__name__)

RECONNECT_DELAY = 1.5


class CameraSession:
    """Runs the camera in its own thread and republishes frames to the UI."""

    def __init__(self, width: int = 320, height: int = 240, fps: int = 30):
        self.mode = (width, height, fps)
        self.sensor: str | None = None
        self.error: str | None = None
        self.status: Status = Status.NOT_FOUND
        self.status_detail = t("session.starting")
        self.connected = False
        self.button = False
        self.stats: dict[str, int] = {}
        # Alternate setting and packet size the bus agreed to, for display.
        self.link: tuple[int, int] | None = None

        self._thread: threading.Thread | None = None
        self._quit = threading.Event()
        self._restart = threading.Event()
        self._lock = threading.Lock()
        self._latest: bytes | None = None
        self._seq = 0
        self._times: deque[float] = deque(maxlen=60)

        # Desired control values. Sliders fire continuously while dragging, so
        # values are coalesced per control instead of queued: applying every
        # intermediate value would stall the stream, each I2C write costing
        # three control transfers and a 4 ms settle.
        self._controls: dict[str, object] = {}
        self._dirty: set[str] = set()
        self._ctl_lock = threading.Lock()

        self._recorder: AviWriter | None = None
        self._rec_lock = threading.Lock()
        self.recording_error: str | None = None

    # -- public API ---------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="eyetoy")
        self._thread.start()

    def close(self) -> None:
        self._quit.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.stop_recording()

    def latest(self) -> tuple[int, bytes | None]:
        """Sequence number and JPEG bytes of the newest frame."""
        with self._lock:
            return self._seq, self._latest

    @property
    def fps(self) -> float:
        times = list(self._times)
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return (len(times) - 1) / span if span > 0 else 0.0

    def set_mode(self, width: int, height: int, fps: int) -> None:
        if (width, height, fps) == self.mode:
            return
        self.mode = (width, height, fps)
        self._restart.set()

    def set_control(self, name: str, value: object) -> None:
        with self._ctl_lock:
            self._controls[name] = value
            self._dirty.add(name)

    # -- recording ----------------------------------------------------------
    @property
    def recording(self) -> bool:
        return self._recorder is not None

    @property
    def recorded_frames(self) -> int:
        recorder = self._recorder
        return recorder.frames if recorder is not None else 0

    def start_recording(self, path: str | Path) -> None:
        """Start writing an AVI. Raises OSError if the file cannot be created."""
        width, height, fps = self.mode
        with self._rec_lock:
            if self._recorder is None:
                self.recording_error = None
                self._recorder = AviWriter(path, width, height, fps)

    def stop_recording(self) -> dict | None:
        """Finish the current recording and return a summary, if any."""
        with self._rec_lock:
            recorder, self._recorder = self._recorder, None
        if recorder is None:
            return None
        measured = recorder.close()
        return {"path": recorder.path, "frames": recorder.frames,
                "fps": measured, "bytes": recorder.path.stat().st_size}

    # -- thread internals ---------------------------------------------------
    def _run(self) -> None:
        while not self._quit.is_set():
            try:
                self._session()
            except Exception as exc:                # noqa: BLE001 - shown in UI
                self.connected = False
                self.link = None
                try:
                    self.status, self.status_detail = probe()
                except Exception as probe_exc:      # noqa: BLE001
                    # A failing probe must not kill this thread: the UI would
                    # then wait on a camera that is never retried.
                    self.status = Status.NOT_FOUND
                    self.status_detail = t("session.usb_unavailable",
                                           error=probe_exc)
                error = (self.status_detail if self.status is not Status.OK
                         else str(exc) if isinstance(exc, EyeToyError)
                         else f"{type(exc).__name__}: {exc}")
                # Retries every 1.5 s: log a failure once, not on every retry.
                if error != self.error:
                    log.warning("camera unavailable: %s", error,
                                exc_info=self.status is Status.OK)
                self.error = error
                # Wait before retrying so a replug or a busy device recovers on
                # its own rather than spinning on the USB stack.
                if self._quit.wait(RECONNECT_DELAY):
                    return

    def _session(self) -> None:
        # Clear before reading the mode, so a change requested during setup is
        # not swallowed by a later clear.
        self._restart.clear()
        width, height, fps = self.mode
        with EyeToy(width, height, fps) as cam:
            self.sensor = cam.bring_up()
            cam.configure()
            with self._ctl_lock:
                self._dirty = set(self._controls)
            self._apply_dirty(cam)
            cam.start(self._on_frame)
            self.link = (cam.alt_setting, cam.packet_size)
            log.info("streaming %dx%d, alt %d (%d B/packet), sensor %s",
                     width, height, *self.link, self.sensor)
            self.connected, self.error = True, None
            self.status, self.status_detail = Status.OK, t("session.ready")
            while not self._quit.is_set() and not self._restart.is_set():
                cam.pump(0.05)
                self.button = cam.button
                self.stats = dict(cam.stats)
                self._apply_dirty(cam)
            cam.stop()
        self.connected = False

    def _apply_dirty(self, cam: EyeToy) -> None:
        with self._ctl_lock:
            if not self._dirty:
                return
            pending = {name: self._controls[name] for name in self._dirty}
            self._dirty.clear()
        for name, value in pending.items():
            setter = getattr(cam, f"set_{name}", None)
            if setter is not None:
                setter(value)

    def _on_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._latest = jpeg
            self._seq += 1
        self._times.append(time.monotonic())
        # Recording taps the untouched sensor JPEG: no re-encoding, no loss,
        # and no dropped frames if the UI stalls. This runs inside the libusb
        # transfer callback, so a write error must never escape - a full disk
        # would otherwise tear down the stream instead of just the recording.
        with self._rec_lock:
            if self._recorder is not None:
                try:
                    self._recorder.add(jpeg)
                except (OSError, ValueError) as exc:
                    failed, self._recorder = self._recorder, None
                    self.recording_error = t("session.recording_interrupted",
                                             error=exc)
                    log.error("recording interrupted (%s): %s",
                              failed.path, exc)
                    # Finish the file as far as possible: with its headers
                    # patched, what was written up to the error stays playable.
                    try:
                        failed.close()
                    except (OSError, ValueError) as close_exc:
                        log.error("file not finalised: %s", close_exc)
