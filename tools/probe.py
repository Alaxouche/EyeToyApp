import usb1

VID, PID = 0x054C, 0x0155

with usb1.USBContext() as ctx:
    for dev in ctx.getDeviceIterator(skip_on_error=True):
        if (dev.getVendorID(), dev.getProductID()) != (VID, PID):
            continue
        print(f"Device {dev.getVendorID():04x}:{dev.getProductID():04x} "
              f"bus {dev.getBusNumber()} addr {dev.getDeviceAddress()}")
        print(f"  USB {dev.getbcdUSB():#06x}  speed={dev.getDeviceSpeed()}  "
              f"class={dev.getDeviceClass()}")
        for cfg in dev.iterConfigurations():
            print(f"  Config #{cfg.getConfigurationValue()}  "
                  f"maxpower={cfg.getMaxPower()}  ifaces={cfg.getNumInterfaces()}")
            for iface in cfg:
                for alt in iface:
                    print(f"    Iface {alt.getNumber()} alt {alt.getAlternateSetting()} "
                          f"class={alt.getClass()}/{alt.getSubClass()}/{alt.getProtocol()} "
                          f"eps={alt.getNumEndpoints()}")
                    for ep in alt:
                        attrs = ep.getAttributes()
                        xfer = {0: "control", 1: "ISOC", 2: "bulk", 3: "interrupt"}[attrs & 3]
                        mps = ep.getMaxPacketSize()
                        # bits 11-12 = additional transactions per microframe (HS only)
                        print(f"        EP {ep.getAddress():#04x} {xfer:9s} "
                              f"maxpacket={mps:5d} interval={ep.getInterval()}")
        try:
            h = dev.open()
            print("  OPEN OK")
            for name, idx in (("manufacturer", dev.getManufacturerDescriptor()),
                              ("product", dev.getProductDescriptor())):
                if idx:
                    print(f"    {name}: {h.getASCIIStringDescriptor(idx)!r}")
            h.close()
        except usb1.USBError as e:
            print(f"  OPEN FAILED: {e}")
