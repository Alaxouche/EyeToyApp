import usb1

VID, PID = 0x054C, 0x0155
# OV519: vendor request 1, wValue=0, wIndex=register, 1 data byte
REQ = 1

with usb1.USBContext() as ctx:
    h = ctx.openByVendorIDAndProductID(VID, PID)
    if h is None:
        raise SystemExit("device not found / not openable")
    h.claimInterface(0)
    print("interface 0 claimed")

    def reg_r(reg):
        return h.controlRead(0xC0, REQ, 0, reg, 1, timeout=500)[0]

    def reg_w(reg, val):
        h.controlWrite(0x40, REQ, 0, reg, bytes([val]), timeout=500)

    # Read a spread of system-controller registers to prove the bus works.
    for reg in (0x00, 0x20, 0x22, 0x25, 0x51, 0x53, 0x54, 0x5a, 0x5d, 0x71, 0x72):
        try:
            print(f"  reg 0x{reg:02x} = 0x{reg_r(reg):02x}")
        except usb1.USBError as e:
            print(f"  reg 0x{reg:02x} -> ERROR {e}")

    # Write/readback test on a scratch-ish register (X offset low byte).
    old = reg_r(0x12)
    reg_w(0x12, 0x5a)
    back = reg_r(0x12)
    reg_w(0x12, old)
    print(f"write/readback on 0x12: wrote 0x5a, read 0x{back:02x} -> "
          f"{'RW OK' if back == 0x5a else 'mismatch'}")

    h.releaseInterface(0)
    h.close()
