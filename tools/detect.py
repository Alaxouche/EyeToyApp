import sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from eyetoy.ov519 import OV519

with OV519() as cam:
    print(f"EyeToy opened (054c:{cam.product_id:04x})")

    cam.init_bridge()
    print("bridge initialised")
    print(f"  reg 0x22 readback = 0x{cam.reg_r(0x22):02x}  (driver notes Windows sees 0x55)")

    cam.sync_sensor()
    print("sensor I2C synced")
    print(f"  manufacturer ID = 0x{cam.i2c_r(0x1c):02x}{cam.i2c_r(0x1d):02x}  (expect 0x7fa2)")

    print(f"SENSOR = {cam.detect_sensor()}")

    print("blinking LED 3x...")
    for _ in range(3):
        cam.set_led(True); time.sleep(0.35)
        cam.set_led(False); time.sleep(0.35)
