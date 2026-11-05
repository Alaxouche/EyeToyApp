"""Low-level control of the OV519 bridge inside a PlayStation 2 EyeToy.

Register semantics, init tables and the I2C/SCCB access pattern are ported from
the Linux gspca driver (drivers/media/usb/gspca/ov519.c, GPL-2.0), which is the
only complete public description of this bridge.

The EyeToy is a USB 1.1 full-speed composite device:
  interface 0 -> vendor-specific video, isochronous IN on 0x81
  interfaces 1/2 -> USB Audio Class (the built-in microphone; Windows owns it)

Only interface 0 is claimed here, so the microphone keeps working normally.
"""

from __future__ import annotations

import enum
import time

import usb1

from .i18n import t

VENDOR_ID = 0x054C
PRODUCT_IDS = (0x0154, 0x0155)

VIDEO_INTERFACE = 0
VIDEO_ENDPOINT = 0x81

# The OV519 uses a single vendor request number for both directions; the
# register index travels in wIndex and the payload is always one byte.
_REQ_IO = 1

# --- bridge registers -------------------------------------------------------
R51x_I2C_W_SID = 0x41
R51x_I2C_SADDR_3 = 0x42
R51x_I2C_SADDR_2 = 0x43
R51x_I2C_R_SID = 0x44
R51x_I2C_DATA = 0x45
R518_I2C_CTL = 0x47

OV519_R10_H_SIZE = 0x10
OV519_R11_V_SIZE = 0x11
OV519_R12_X_OFFSETL = 0x12
OV519_R13_X_OFFSETH = 0x13
OV519_R14_Y_OFFSETL = 0x14
OV519_R15_Y_OFFSETH = 0x15
OV519_R16_DIVIDER = 0x16
OV519_R20_DFR = 0x20
OV519_R25_FORMAT = 0x25
OV519_R51_RESET1 = 0x51
OV519_R54_EN_CLK1 = 0x54
OV519_R57_SNAPSHOT = 0x57
OV519_GPIO_DATA_OUT0 = 0x71
OV519_GPIO_IO_CTRL0 = 0x72

# --- sensor, reached over the bridge's I2C master ---------------------------
OV7xx0_SID = 0x42
OV7610_REG_ID_HIGH = 0x1C  # manufacturer ID MSB, always 0x7f
OV7610_REG_ID_LOW = 0x1D   # manufacturer ID LSB, always 0xa2
OV7610_REG_COM_I = 0x29

I2C_DETECT_TRIES = 10

# Bridge bring-up. The comments are the driver's own notes; the LED pin must be
# put in output mode with bit 4 clear or sensor detection fails.
INIT_519 = (
    (0x5A, 0x6D),                  # EnableSystem
    (0x53, 0x9B),                  # do not enable the microcontroller
    (OV519_R54_EN_CLK1, 0xFF),     # bit 2 enables the JPEG engine
    (0x5D, 0x03),
    (0x49, 0x01),
    (0x48, 0x00),
    (OV519_GPIO_IO_CTRL0, 0xEE),   # LED pin to output mode
    (OV519_R51_RESET1, 0x0F),
    (OV519_R51_RESET1, 0x00),
    (0x22, 0x00),
)


class EyeToyError(RuntimeError):
    pass


class Status(enum.Enum):
    """Why the camera is or is not usable right now."""

    OK = "ok"
    NOT_FOUND = "not_found"
    DRIVER_MISSING = "driver_missing"
    BUSY = "busy"


def probe() -> tuple[Status, str]:
    """Report whether the camera can be opened, and why not when it cannot.

    libusb enumerates every USB device on Windows, including ones it has no
    driver for, so a device that is present but unopenable tells us the
    WinUSB/libusbK binding is missing rather than the camera.
    """
    with usb1.USBContext() as ctx:
        for dev in ctx.getDeviceIterator(skip_on_error=True):
            if dev.getVendorID() != VENDOR_ID:
                continue
            if dev.getProductID() not in PRODUCT_IDS:
                continue
            try:
                handle = dev.open()
            except usb1.USBErrorNotSupported:
                return Status.DRIVER_MISSING, t("probe.not_bound")
            except usb1.USBErrorAccess:
                return Status.DRIVER_MISSING, t("probe.access_denied")
            except usb1.USBError as exc:
                return Status.DRIVER_MISSING, t("probe.open_failed", error=exc)
            try:
                handle.claimInterface(VIDEO_INTERFACE)
                handle.releaseInterface(VIDEO_INTERFACE)
            except usb1.USBError:
                return Status.BUSY, t("probe.busy")
            finally:
                handle.close()
            return Status.OK, t("session.ready")
    return Status.NOT_FOUND, t("probe.not_found")


class OV519:
    """Register-level handle on the bridge. Use as a context manager."""

    def __init__(self, timeout_ms: int = 500):
        self._timeout = timeout_ms
        self._ctx: usb1.USBContext | None = None
        self._h: usb1.USBDeviceHandle | None = None
        self.product_id: int | None = None
        self.sensor: str | None = None

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "OV519":
        self._ctx = usb1.USBContext()
        self._ctx.open()
        for pid in PRODUCT_IDS:
            handle = self._ctx.openByVendorIDAndProductID(VENDOR_ID, pid)
            if handle is not None:
                self._h, self.product_id = handle, pid
                break
        else:
            self._ctx.close()
            raise EyeToyError(t("probe.not_accessible"))
        self._h.claimInterface(VIDEO_INTERFACE)
        return self

    def __exit__(self, *exc) -> None:
        if self._h is not None:
            try:
                self.set_led(False)
                self._h.releaseInterface(VIDEO_INTERFACE)
            except usb1.USBError:
                pass
            self._h.close()
        if self._ctx is not None:
            self._ctx.close()

    # -- bridge registers ---------------------------------------------------
    def reg_w(self, reg: int, value: int) -> None:
        self._h.controlWrite(0x40, _REQ_IO, 0, reg, bytes([value]), self._timeout)

    def reg_r(self, reg: int) -> int:
        return self._h.controlRead(0xC0, _REQ_IO, 0, reg, 1, self._timeout)[0]

    def reg_w_mask(self, reg: int, value: int, mask: int) -> None:
        self.reg_w(reg, (self.reg_r(reg) & ~mask) | (value & mask))

    # -- sensor I2C ---------------------------------------------------------
    # The OV519 inherits the OV518 three-phase I2C sequence: load the register
    # index and data into the bridge, then kick the controller via R518_I2C_CTL.
    # Reading back the control register is the driver's way of waiting for the
    # transaction to retire, so the discarded reads below are load-bearing.
    def i2c_w(self, reg: int, value: int) -> None:
        self.reg_w(R51x_I2C_SADDR_3, reg)
        self.reg_w(R51x_I2C_DATA, value)
        self.reg_w(R518_I2C_CTL, 0x01)  # 3-byte write cycle
        time.sleep(0.004)
        self.reg_r(R518_I2C_CTL)

    def i2c_r(self, reg: int) -> int:
        self.reg_w(R51x_I2C_SADDR_2, reg)
        self.reg_w(R518_I2C_CTL, 0x03)  # 2-byte write cycle
        self.reg_r(R518_I2C_CTL)
        self.reg_w(R518_I2C_CTL, 0x05)  # 2-byte read cycle
        self.reg_r(R518_I2C_CTL)
        return self.reg_r(R51x_I2C_DATA)

    def set_slave_ids(self, slave: int) -> None:
        self.reg_w(R51x_I2C_W_SID, slave)
        self.reg_w(R51x_I2C_R_SID, slave + 1)

    # -- bring-up -----------------------------------------------------------
    def set_led(self, on: bool) -> None:
        self.reg_w_mask(OV519_GPIO_DATA_OUT0, 1 if on else 0, 0x01)

    def init_bridge(self) -> None:
        for reg, value in INIT_519:
            self.reg_w(reg, value)

    def sync_sensor(self, slave: int = OV7xx0_SID) -> None:
        """Reset the sensor and wait for its I2C ID registers to answer."""
        self.set_slave_ids(slave)
        for attempt in range(I2C_DETECT_TRIES):
            self.i2c_w(0x12, 0x80)  # COM7 reset
            time.sleep(0.15)
            if (self.i2c_r(OV7610_REG_ID_HIGH) == 0x7F
                    and self.i2c_r(OV7610_REG_ID_LOW) == 0xA2):
                return
            self.i2c_r(0x00)  # dummy read to resync
        raise EyeToyError("sensor did not answer on I2C after reset")

    def detect_sensor(self) -> str:
        """Identify the imager. The EyeToy Namtai carries an OV7648."""
        com_i = self.i2c_r(OV7610_REG_COM_I)
        if com_i & 3 != 0:
            # OV7610/OV7620 family variants; not what an EyeToy ships with.
            self.sensor = f"OV76xx (COM_I=0x{com_i:02x}, unexpected for EyeToy)"
            return self.sensor
        high, low = self.i2c_r(0x0A), self.i2c_r(0x0B)
        if high != 0x76:
            self.sensor = f"OV7620 (PID 0x{high:02x}{low:02x})"
            return self.sensor
        self.sensor = {
            0x30: "OV7630/OV7635 (unsupported)",
            0x40: "OV7645",
            0x45: "OV7645B",
            0x48: "OV7648",
            0x60: "OV7660",
        }.get(low, f"unknown OV76{low:02x}")
        return self.sensor
