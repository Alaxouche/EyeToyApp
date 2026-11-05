"""Video streaming from the EyeToy: mode setup plus isochronous capture.

The bridge emits one frame as a run of isochronous packets (896 bytes each at
best, less when the bus cannot reserve that much). A frame is
delimited by 16-byte headers (magic ff ff ff, then 0x50 for SOF / 0x51 for EOF);
everything between them is JPEG payload produced by the OV519 compressor.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

import usb1

from .i18n import t

from .ov519 import (
    OV519, EyeToyError, VIDEO_ENDPOINT, VIDEO_INTERFACE,
    OV519_R10_H_SIZE, OV519_R11_V_SIZE, OV519_R12_X_OFFSETL,
    OV519_R13_X_OFFSETH, OV519_R14_Y_OFFSETL, OV519_R15_Y_OFFSETH,
    OV519_R16_DIVIDER, OV519_R20_DFR, OV519_R25_FORMAT, OV519_R51_RESET1,
    OV519_R54_EN_CLK1,
)

log = logging.getLogger(__name__)

# The video interface offers alternate settings 1-4 at 384, 512, 768 and 896
# bytes per isochronous packet. The largest is tried first, but a controller
# already carrying other isochronous devices (USB headsets, audio interfaces)
# may refuse to reserve that much: SET_INTERFACE then fails with an I/O error.
# Falling back to a smaller packet costs little - measured on an AMD xHCI port
# shared with three audio devices, which refused alt 4: alt 3 and alt 2 both
# gave 29 fps in QVGA and 14.4 fps in VGA, every frame decodable. The Linux
# gspca core walks down the alt settings in the same way.
#
# Used when the descriptors cannot be read for some reason.
FALLBACK_ALT_SETTINGS = ((4, 896), (3, 768), (2, 512), (1, 384))

# At full speed one packet takes 1 ms, so this queues 16 x 64 = 1.02 s of bus
# time ahead. A transfer's length sets the latency floor, since it only
# completes once its whole window has elapsed: 16 ms here.
#
# The ceiling is not ours to choose. WinUSB registers isochronous buffers up
# front and tolerates about 1024 packets outstanding; past that, cancelling the
# queue crashes inside libusb rather than failing cleanly. MAX_QUEUED_PACKETS
# keeps any configuration on the safe side of that.
#
# libusbK has no such limit but the opposite temperament: it wants a deep queue,
# and stalls in bursts below roughly 2 s of headroom. WinUSB is steady at 1 s -
# zero gaps, 48 ms worst case - so the driver this application installs is also
# the one these numbers suit.
PACKETS_PER_TRANSFER = 16
TRANSFERS_IN_FLIGHT = 64
MAX_QUEUED_PACKETS = 1024

HEADER_SIZE = 16
SOF, EOF = 0x50, 0x51

# (width, height) -> qvga flag, as encoded in the driver mode .priv field
MODES = {(640, 480): 0, (320, 240): 1}

# The fps argument is a request aimed at the sensor, not a guarantee. QVGA
# reaches about 28.7 fps; VGA is capped near 13.8 by the USB 1.1 bus whatever
# the sensor is told, so VGA should still ask for 30 - asking for 15 engages
# the clock divider below and halves an already bus-limited stream.

# Bridge registers for streaming mode. Undocumented entries are kept verbatim
# from the driver; 0xa2-0xa5 and 0x17/0x37/0xff have no public description.
MODE_INIT_519 = (
    (0x5D, 0x03),                  # turn off suspend mode
    (0x53, 0x9F),
    (OV519_R54_EN_CLK1, 0x0F),     # bit 2 = JPEG enable
    (0xA2, 0x20),
    (0xA3, 0x18),
    (0xA4, 0x04),
    (0xA5, 0x28),
    (0x37, 0x00),                  # SetUsbInit
    (0x55, 0x02),                  # 4.096 MHz audio clock
    (0x22, 0x1D),                  # both fields, YUV input
    (0x17, 0x50),
    (0x37, 0x00),
    (0x40, 0xFF),                  # I2C timeout counter
    (0x46, 0x00),                  # I2C clock prescaler
    (0x59, 0x04),
    (0xFF, 0x00),
)

# Per frame rate: bridge registers 0xa4 and 0x23, plus the sensor clock divider
# written to CLKRC. Leaving CLKRC alone is not an option - the sensor keeps
# whatever divider the previous session left behind, so the frame rate drifts
# downwards run after run.
FRAME_RATE_REGS = {
    30: (0x0C, 0xFF, 0), 25: (0x0C, 0x1F, 0), 20: (0x0C, 0x1B, 0),
    15: (0x04, 0xFF, 1), 10: (0x04, 0x1F, 1), 5: (0x04, 0x1B, 1),
}


def trim_jpeg(buf: bytes | bytearray) -> bytes:
    """Cut the zero padding the last isochronous packet adds after the EOI."""
    end = buf.rfind(b"\xff\xd9")
    return bytes(buf if end < 0 else buf[:end + 2])


def order_alt_settings(
        candidates: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """(alt, packet size) pairs worth trying, largest packet first."""
    usable = {(alt, size) for alt, size in candidates if alt > 0 and size > 0}
    return sorted(usable, key=lambda pair: (pair[1], pair[0]), reverse=True)


class BandwidthError(EyeToyError):
    """No alternate setting could reserve isochronous bandwidth."""


class EyeToy(OV519):
    """A configured, streamable EyeToy."""

    def __init__(self, width: int = 320, height: int = 240, fps: int = 30,
                 timeout_ms: int = 500):
        super().__init__(timeout_ms)
        if (width, height) not in MODES:
            raise ValueError(f"unsupported mode {width}x{height}")
        if fps not in FRAME_RATE_REGS:
            raise ValueError(f"unsupported frame rate {fps}")
        self.width, self.height, self.fps = width, height, fps
        self.qvga = MODES[(width, height)]
        self.streaming = False
        self.button = False
        self.alt_setting: int | None = None
        self.packet_size: int | None = None
        # Capture statistics, useful when the picture comes out wrong.
        self.stats = {"packets": 0, "bytes": 0, "frames": 0, "discarded": 0,
                      "iso_errors": 0}
        self._transfers: list = []
        # Transfers that never came back from cancellation. libusb still owns
        # their buffers, so they are kept referenced for the object's lifetime
        # rather than freed under it.
        self._orphans: list = []
        self._token: object | None = None
        self._buf: bytearray | None = None
        self._on_frame: Callable[[bytes], None] | None = None

    # -- configuration ------------------------------------------------------
    def bring_up(self) -> str:
        """Full power-on sequence; returns the detected sensor name."""
        self.init_bridge()
        self.sync_sensor()
        sensor = self.detect_sensor()
        if not sensor.startswith("OV764"):
            raise EyeToyError(f"unexpected sensor for an EyeToy: {sensor}")
        # norm_7640: reset, then the mode the driver leaves the sensor in
        self.i2c_w(0x12, 0x80)
        time.sleep(0.15)
        self.i2c_w(0x12, 0x14)
        return sensor

    def configure(self) -> None:
        """Program bridge and sensor for the requested mode and frame rate."""
        for reg, value in MODE_INIT_519:
            self.reg_w(reg, value)
        self.reg_w_mask(OV519_R20_DFR, 0x10, 0x10)  # 8-bit input, OV764x only

        self.reg_w(OV519_R10_H_SIZE, self.width >> 4)
        self.reg_w(OV519_R11_V_SIZE, self.height >> 3)
        # The OV7648 needs a one-pixel horizontal nudge in QVGA.
        self.reg_w(OV519_R12_X_OFFSETL, 0x01 if self.qvga else 0x00)
        self.reg_w(OV519_R13_X_OFFSETH, 0x00)
        self.reg_w(OV519_R14_Y_OFFSETL, 0x00)
        self.reg_w(OV519_R15_Y_OFFSETH, 0x00)
        self.reg_w(OV519_R16_DIVIDER, 0x00)
        self.reg_w(OV519_R25_FORMAT, 0x03)          # YUV422
        self.reg_w(0x26, 0x00)

        reg_a4, reg_23, _clockdiv = FRAME_RATE_REGS[self.fps]
        self.reg_w(0xA4, reg_a4)
        self.reg_w(0x23, reg_23)

        self._configure_sensor_window()

    def _configure_sensor_window(self) -> None:
        """Sensor-side mode and cropping window.

        The driver warns in capitals that a wrong window yields all-zero
        isochronous data, so these magic bases are not to be tidied up.
        """
        qvga = self.qvga
        self.i2c_w_mask(0x14, 0x20 if qvga else 0x00, 0x20)
        self.i2c_w_mask(0x28, 0x00 if qvga else 0x20, 0x20)
        # Undocumented, but removes a bad vertical shake in QVGA.
        self.i2c_w_mask(0x2D, 0x40 if qvga else 0x00, 0x40)
        self.i2c_w_mask(0x67, 0xF0 if qvga else 0x90, 0xF0)
        # Allow higher automatic gain, which allows higher frame rates.
        self.i2c_w_mask(0x74, 0x20 if qvga else 0x00, 0x20)
        self.i2c_w_mask(0x12, 0x04, 0x04)           # auto white balance on

        # Clock programming, and it must land before the window registers.
        self.i2c_w(0x11, FRAME_RATE_REGS[self.fps][2])

        hwbase, vwbase = 0x1A, 0x03
        hwscale, vwscale = (1, 0) if qvga else (2, 1)
        self.i2c_w(0x17, hwbase)
        self.i2c_w(0x18, (hwbase + (self.width >> hwscale)) & 0xFF)
        self.i2c_w(0x19, vwbase)
        self.i2c_w(0x1A, (vwbase + (self.height >> vwscale)) & 0xFF)

    def i2c_w_mask(self, reg: int, value: int, mask: int) -> None:
        self.i2c_w(reg, (self.i2c_r(reg) & ~mask) | (value & mask))

    # -- image controls -----------------------------------------------------
    # The OV7648 exposes fewer knobs than its siblings: there is no contrast
    # register and no hardware mirror, so flipping is done in software.
    def set_brightness(self, value: int) -> None:
        self.i2c_w(0x06, value & 0xFF)

    def set_saturation(self, value: int) -> None:
        self.i2c_w(0x03, value & 0xF0)

    def set_exposure(self, value: int) -> None:
        self.i2c_w(0x10, value & 0xFF)

    def set_autogain(self, on: bool) -> None:
        # gspca's setautogain writes mask 0x05, but it only offers that control
        # on the OV2610 and OV9600; for the OV7640/7648 it exposes brightness,
        # saturation and light frequency, nothing else. On the OV7648, bit 2 of
        # this register turns the stream into all-zero data - a flat green
        # picture once decoded. Measured instead: the register powers up at
        # 0xa3, and with bit 0 set the sensor rewrites the exposure register on
        # its own (0x08 written, 0x1b read back a second later), while with bit
        # 0 clear the written exposure holds. Bit 0 is the automatic exposure.
        self.i2c_w_mask(0x13, 0x01 if on else 0x00, 0x01)

    # -- streaming ----------------------------------------------------------
    def _alt_settings(self) -> list[tuple[int, int]]:
        """The video endpoint's alternate settings, read from the descriptors."""
        found = []
        try:
            for setting in self._h.getDevice().iterSettings():
                if setting.getNumber() != VIDEO_INTERFACE:
                    continue
                for endpoint in setting:
                    if endpoint.getAddress() == VIDEO_ENDPOINT:
                        # Bits 11-12 encode extra transactions per microframe,
                        # meaningless at full speed; the size is in bits 0-10.
                        found.append((setting.getAlternateSetting(),
                                      endpoint.getMaxPacketSize() & 0x7FF))
        except usb1.USBError as exc:
            log.warning("descriptors unreadable (%s), using defaults", exc)
        return order_alt_settings(found) or list(FALLBACK_ALT_SETTINGS)

    def _select_alt_setting(self) -> None:
        """Take the largest alternate setting the bus agrees to reserve."""
        refused = []
        for alt, size in self._alt_settings():
            try:
                self._h.setInterfaceAltSetting(VIDEO_INTERFACE, alt)
            except (usb1.USBErrorIO, usb1.USBErrorNoMem, usb1.USBErrorPipe,
                    usb1.USBErrorOverflow) as exc:
                refused.append(f"alt {alt}: {exc}")
                continue
            if refused:
                log.info("limited bandwidth, alt %d (%d B/packet); refused: %s",
                         alt, size, "; ".join(refused))
            self.alt_setting, self.packet_size = alt, size
            return
        raise BandwidthError(t("camera.bandwidth"))

    def start(self, on_frame: Callable[[bytes], None]) -> None:
        if self.streaming:
            raise EyeToyError("already streaming")
        self._on_frame = on_frame
        self._buf = None
        self._select_alt_setting()
        # ov51x_restart: pulse RESET1, then re-arm the framer
        self.reg_w(OV519_R51_RESET1, 0x0F)
        self.reg_w(OV519_R51_RESET1, 0x00)
        self.reg_w(0x22, 0x1D)
        self.set_led(True)
        self.streaming = True
        # Transfers carry the token of the run that created them, so one left
        # over from a previous run cannot resubmit itself into this one.
        self._token = token = object()
        self._transfers = []
        count = min(TRANSFERS_IN_FLIGHT,
                    max(1, MAX_QUEUED_PACKETS // PACKETS_PER_TRANSFER))
        for _ in range(count):
            transfer = self._h.getTransfer(iso_packets=PACKETS_PER_TRANSFER)
            transfer.setIsochronous(
                VIDEO_ENDPOINT, PACKETS_PER_TRANSFER * self.packet_size,
                callback=lambda t, tok=token: self._transfer_done(t, tok))
            transfer.submit()
            self._transfers.append(transfer)

    def stop(self) -> None:
        if not self.streaming:
            return
        self.streaming = False
        for transfer in self._transfers:
            try:
                transfer.cancel()
            except usb1.USBError:
                pass
        # Every transfer must be reaped before its object can be dropped, or
        # libusb would be left writing into freed buffers. With a deep queue
        # cancellation takes a moment, so allow for it - and on the rare
        # timeout, keep the stragglers referenced rather than risk that.
        deadline = time.monotonic() + 3.0
        while any(t.isSubmitted() for t in self._transfers):
            if time.monotonic() > deadline:
                break
            self._ctx.handleEventsTimeout(0.05)
        self._orphans += [t for t in self._transfers if t.isSubmitted()]
        self._transfers = []
        # ov51x_stop, then drop back to the zero-bandwidth alt setting
        self.reg_w(OV519_R51_RESET1, 0x0F)
        self.reg_w(OV519_R51_RESET1, 0x00)
        self.reg_w(0x22, 0x00)
        self.set_led(False)
        # Under WinUSB, going back to alt 0 after streaming can fail with an
        # I/O error even once every transfer is reaped and freed (seen on every
        # stop on one AMD xHCI port). It only gives the bandwidth back early:
        # releasing the interface on close does the same, and the next session
        # selects its alt setting afresh. Not worth tearing the session down.
        try:
            self._h.setInterfaceAltSetting(VIDEO_INTERFACE, 0)
        except usb1.USBError as exc:
            log.debug("going back to alt 0 refused: %s", exc)

    def pump(self, seconds: float) -> None:
        """Drive the libusb event loop for a while, dispatching frames."""
        end = time.monotonic() + seconds
        while self.streaming and time.monotonic() < end:
            self._ctx.handleEventsTimeout(0.1)

    # -- isochronous plumbing ----------------------------------------------
    def _transfer_done(self, transfer, token: object) -> None:
        if token is not self._token:
            return                      # left over from a previous run
        for status, data in transfer.iterISO():
            if status != usb1.TRANSFER_COMPLETED:
                self.stats["iso_errors"] += 1
                continue
            if data:
                self.stats["packets"] += 1
                self.stats["bytes"] += len(data)
                self._on_packet(bytes(data))
        if self.streaming:
            try:
                transfer.submit()
            except usb1.USBError:
                pass

    def _on_packet(self, data: bytes) -> None:
        if (len(data) >= HEADER_SIZE
                and data[0] == 0xFF and data[1] == 0xFF and data[2] == 0xFF):
            if data[3] == SOF:
                payload = data[HEADER_SIZE:]
                # A real frame opens with a JPEG SOI marker; anything else is
                # the bridge sending an initial frame without image data.
                self._buf = bytearray(payload) if payload[:1] == b"\xff" else None
                return
            if data[3] == EOF:
                self.button = bool(data[11] & 1)
                buf, self._buf = self._buf, None
                if data[9] != 0 or buf is None:
                    self.stats["discarded"] += 1
                    return
                self.stats["frames"] += 1
                if self._on_frame is not None:
                    self._on_frame(trim_jpeg(buf))
                return
        if self._buf is not None:
            self._buf += data
