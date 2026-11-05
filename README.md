# EyeToy Studio

A user-space driver and viewer for the PlayStation 2 **EyeToy** camera on
**Windows 10 and 11**. There's no kernel driver and nothing to sign: everything
goes through libusb.

Windows never had a driver for this camera (it isn't UVC), and the original
XP/Vista drivers are unsigned kernel drivers, which Windows 10 and later refuse
to load. This project gets around that by talking to the camera entirely from
user space.

## Status

It works. Measured on an EyeToy Namtai `054c:0155` (**OV519** bridge,
**OV7648** sensor) with the WinUSB driver, counting only unique frames by hash:

| Mode | Frame rate | Notes |
|---|---|---|
| 320 × 240 | **37 fps** | faster than the preset's nominal 30 fps |
| 320 × 240 (15 fps) | ~18 fps | sensor clock divider engaged |
| 640 × 480 | **18.3 fps** | capped by USB 1.1 (12 Mbps) |

No isochronous errors across all the test captures.

The driver matters: with libusbK the same measurements gave 30 and 13.8 fps.
WinUSB, which is what the app installs, is noticeably faster on this hardware.

### Supported systems

| System | |
|---|---|
| Windows 11 x64 | tested |
| Windows 10 x64 | supported (Python 3.14 requires Windows 10) |
| Windows 8.1 and older, 32-bit Windows | no: the binary is x64 and Python 3.14 dropped them |
| Windows 11 ARM64 | no: the driver installer only ships `installer_x64.exe` |
| S mode, or Smart App Control turned on | blocked until the binary is signed |

There's nothing to install alongside it: the C++ runtime is bundled in the
executable. Only the virtual camera (OBS Studio, through `winget`) and the
manual driver install (which downloads Zadig) need anything extra, and only if
you use them.

## Features

- Live preview with a running frame rate counter
- Digital zoom up to 6× with the mouse wheel, drag to pan
- PNG snapshots with the space bar or the camera's own button
- Video recording to MJPEG AVI, with no re-encoding and no quality loss
- Virtual camera for Discord, OBS and Teams (see the limitations below)
- Sensor controls: brightness, exposure, saturation, auto exposure
- Mirror, smoothing, automatic reconnect when the camera is unplugged
- Settings remembered between launches
- Falls back to a lower isochronous bandwidth when the USB controller is busy
- Sharp on displays scaled to 125%, 150% and above
- English interface by default, French available under *Settings → Language*.
  The switch is immediate and doesn't interrupt the stream or a recording in
  progress.

## Installing the driver

Windows doesn't assign any driver to this device, so interface 0 has to be
bound to **WinUSB**.

It takes one click. The app notices the missing driver, offers *Install
driver*, and does it: one UAC prompt, about two seconds, and the camera shows
up. No reboot needed, the session reconnects on its own.

Behind the button is `vendor/wdi-simple.exe`, built from
[libwdi](https://github.com/pbatard/libwdi) for WinUSB only. It doesn't carry
any third-party driver: `WinUSB.sys` comes with Windows, and the generated INF
defers to the system's `winusb.inf`.

Leave interfaces 1 and 2 alone. They're the built-in microphone, a USB Audio
Class device that Windows already handles. The installer only touches
interface 0.

The *Driver...* button at the bottom of the panel, or *Settings → Camera
driver...*, brings this window back whenever you need it: reinstall, go
through Zadig, or uninstall.

`wdi-simple.exe` reads its command line in the ANSI code page, while libwdi
treats paths as UTF-8, so an accented character anywhere in a path gets
mangled. The app therefore extracts the driver files to
`%LOCALAPPDATA%\EyeToyStudio\driver` when that path is plain ASCII, and to
`%ProgramData%\EyeToyStudio\driver` otherwise (on a Windows account with an
accented name, for example).

### What the install does to your machine

Windows refuses any INF whose catalog isn't signed by a trusted certificate,
and there's no way around that. So the installer generates a catalog, creates a
**self-signed certificate** specific to the device, adds it to the machine's
`Root` and `TrustedPublisher` stores, signs the catalog with it, and then
destroys the private key.

This is exactly how Zadig works (libwdi is its engine), and it's worth knowing
before you click. To undo it, use *Driver... → Uninstall*. After a UAC prompt,
the app removes the driver packages libwdi generated for the EyeToy's video
interface (`pnputil /delete-driver ... /uninstall`), then removes their
certificate from both stores. Nothing else is touched. To do it by hand, use
`certlm.msc` for the certificate and Device Manager for the driver.

Details, the patches applied and how to rebuild it are in
[`vendor/README.md`](vendor/README.md).

### Manual method

The *Manual method* button downloads the latest official
[Zadig](https://zadig.akeo.ie/), **checks its Authenticode signature**
(publisher *Akeo Consulting*) before running anything, and launches it
elevated. Use it to go back to libusbK, or as a fallback if the automatic
install fails:

1. *Options* → *List All Devices*
2. Pick **EyeToy USB camera Namtai (Interface 0)**
3. Target **WinUSB** (or **libusbK**), then *Replace Driver*

The signature is only accepted if the certificate is valid **and** its common
name is exactly *Akeo Consulting*.

## Virtual camera (Discord, OBS, Teams...)

Tick *Virtual camera* and the EyeToy shows up as a webcam in other
applications.

Frames go out through the **OBS Studio** virtual camera device. If it's
missing, the app offers *Install support* and installs it silently with
`winget`. **OBS doesn't need to be running afterwards**: its installer
registers the DirectShow filter, and the app feeds it directly.

This dependency can't be avoided. Windows won't let an unsigned, unpackaged
program register its own video device (`MFCreateVirtualCamera` requires a
signed MSIX app), and OBS ships the only free virtual device that is
WHQL-signed and installs without user interaction.

Zoom applies to the virtual output, but the output always stays at the
sensor's native resolution, so the format never changes under the apps reading
it.

## Usage

### Executable

`.\build.ps1` produces `dist\EyeToyStudio.exe`, a single 31 MB file with no
Python or other dependency. You can put it anywhere, `Program Files` included:
it never writes next to itself.

| What | Where |
|---|---|
| Photos and videos | `Pictures\EyeToy Studio` (follows OneDrive redirection), or the folder picked in *Settings → Captures folder...* |
| Settings | `%LOCALAPPDATA%\EyeToyStudio\settings.json`: language, mode, image settings, captures folder |
| Log | `%LOCALAPPDATA%\EyeToyStudio\eyetoy.log` |

If something misbehaves, check the log first. The binary has no console, so
every error ends up there.

Windows SmartScreen will warn that the binary isn't signed: *More info* → *Run
anyway*. Smart App Control has no such escape hatch, so on a machine where
it's on you need a signed binary (see *Building the executable*).

### From source

Python 3.14, x64:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
```

`requirements.txt` only lists runtime dependencies; `requirements-dev.txt`
adds a pinned PyInstaller.

### Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

No camera needed. They cover the AVI muxer, frame reassembly, alt setting
selection, zoom geometry, settings, the translation catalog (every string
exists in both languages with the same placeholders, and every key the code
uses exists), and argument passing to the driver installer, which runs in
extract-only mode, without elevation and without touching the system.

### Building the executable

```powershell
.\build.ps1
```

The script runs the tests, builds the binary with its icon and version info,
then relaunches it from a temporary folder to check that it really is
self-contained, and prints its health report.

**Signing.** If `EYETOY_SIGN_THUMBPRINT` holds the thumbprint of an installed
code signing certificate, the script signs `wdi-simple.exe` before bundling
it, then the final binary, with `signtool` from the Windows SDK. That's what
removes the SmartScreen warning and gets the app past Smart App Control.

The icon is an original drawing generated by `tools\make_icon.py`; run it
again to regenerate `assets\eyetoy.ico`.

A GitHub Actions workflow (`.github/workflows/build.yml`) does the same on a
clean Windows runner and uploads the executable as an artifact.

### Shortcuts

| Key | Action |
|---|---|
| `Space` | snapshot |
| `R` | start / stop recording |
| `0` | reset zoom and pan |
| `Esc` | quit |

### Menus

| Menu | Item | What it does |
|---|---|---|
| *Settings* | *Language* | English or French, applied immediately |
| | *Captures folder...* | choose where photos and videos go |
| | *Use the default captures folder* | go back to `Pictures\EyeToy Studio` |
| | *Open captures folder* | open that folder in Explorer |
| | *Restore default image settings* | brightness, exposure, saturation, auto exposure, mirror, smoothing |
| | *Camera driver...* | install, repair or uninstall the driver |
| *Help* | *Open log file* | open `eyetoy.log` |
| | *About EyeToy Studio* | version, license, file locations |

Every choice is saved and restored on the next launch.

## Known limitations

- The virtual camera relies on OBS Studio (one-click install from the app, see
  above). It hasn't been tested end to end in a third-party app yet.
- Installing the driver puts a self-signed certificate in the machine's trust
  store. That's unavoidable for a generic driver, and explained above.
- The frame rate depends on the bus. The EyeToy is USB 1.1, and other
  isochronous devices on the same controller (a USB headset, an audio
  interface, another webcam) can deny it full bandwidth. The app then steps
  down to a smaller alt setting on its own (896 → 768 → 512 → 384 bytes per
  packet), which costs very little: on a port that refused the maximum it
  still ran at 29 fps in 320 × 240 and 20 fps in 640 × 480. The alt setting in
  use is shown under the stats and written to the log. If even the smallest
  one is refused, try another port.
- Image quality is from 2003: noisy in low light, fixed focus. It's a
  nostalgia piece, not a webcam for video calls.

## Architecture

```
app.py                  Tkinter UI, render loop, DPI handling
eyetoy/session.py       the thread that owns every USB call
eyetoy/camera.py        video mode, alt setting choice, isochronous transfers
eyetoy/ov519.py         bridge registers, sensor I²C, init, diagnostics
eyetoy/recorder.py      MJPEG AVI muxer
eyetoy/vcam.py          virtual camera output
eyetoy/setup_driver.py  driver install, Zadig, uninstall
eyetoy/view.py          zoom geometry
eyetoy/settings.py      persistent settings
eyetoy/i18n.py          UI strings, English and French
eyetoy/paths.py         folders: captures, data, bundled resources
eyetoy/applog.py        file logging
assets/                 icon (generated by tools/make_icon.py)
tests/                  unit tests, no hardware needed
vendor/                 wdi-simple.exe, built from libwdi, and its patches
```

Only one thread touches libusb. The UI reads the latest frame under a lock and
pushes settings through a coalescing map, so dragging a slider causes one I²C
write per cycle, not one per pixel the slider moves.

### How it works

The EyeToy is a composite USB 1.1 device, and not a UVC one:

- **interface 0**: vendor-specific video, isochronous endpoint `0x81`, four alt
  settings (384 / 512 / 768 / **896** bytes per packet);
- **interfaces 1 and 2**: USB Audio Class, the built-in microphone.

Bridge registers are read and written with vendor control transfers:
`bRequest = 1`, the register in `wIndex`, one data byte. The OV7648 sensor sits
behind the bridge's I²C master and is reached with the three-step sequence
inherited from the OV518.

### Sensor registers

For the OV7648, gspca only exposes three controls: brightness (`0x06`),
saturation (`0x03`) and power line frequency. Its `setautogain`, which writes
mask `0x05` into `0x13`, is meant for the OV2610 and OV9600 only. On the
OV7648, bit 2 empties the stream and every decoded frame comes out flat green.
Measuring it instead: `0x13` reads `0xa3` at power-up, and with bit 0 set the
sensor rewrites the exposure register `0x10` on its own, while with bit 0
clear the written value sticks. So bit 0 is auto exposure, and it's the only
bit the checkbox touches. The *Exposure* slider is greyed out while auto
exposure is on.

A frame arrives as a run of isochronous packets delimited by 16-byte headers:
magic `ff ff ff`, then `0x50` (start) or `0x51` (end). In the end header, byte
9 flags an empty frame and byte 11 carries the state of the camera's button.

Contrary to what you often read about this family of bridges, the OV519 here
produces a **complete JFIF**: APP0, quantization tables, all four Huffman
tables, SOF0, SOS, EOI. There are no tables to inject, only the zero padding
of the last packet to trim. That's also why recording is free: frames go into
the AVI container as they are, without re-encoding.

### The clock divider trap

In the Linux driver, `mode_init_ov_sensor_regs` ends by programming the clock
with `i2c_w(0x11, clockdiv)`, which is easy to miss when porting. Without it,
the sensor keeps whatever divider the previous session left behind and the
frame rate drifts from one launch to the next. With it, behaviour is
deterministic and the divider halves the rate exactly (28.7 → 14.2 fps in
QVGA, 13.8 → 6.7 in VGA).

That's also why VGA mode asks for 30 fps and not 15: the bus already limits it
to about 13.8 fps, and engaging the divider would only cut that in half.

### Isochronous queue depth

An isochronous packet lasts 1 ms. The app keeps 16 packets × 64 transfers in
flight, which is **1.02 s of bus time queued ahead**, for 16 ms of latency. A
transfer only completes once its whole window has elapsed, and that sets the
floor.

The two drivers behave in opposite ways, and these numbers come from that.

**libusbK wants a deep queue.** With less than about 2 s of headroom, the queue
drains faster than Windows refills it and the stream stutters: frames arrive
in bunches at the end of each transfer, with half-second gaps in between. The
pattern reproduces every time:

| Queued ahead | Frame rate | Gaps > 100 ms | Longest gap |
|---|---|---|---|
| 0.5 s | 10.9 fps | 3 | 576 ms |
| 1.0 s | 14.4 fps | 2 | 576 ms |
| 2.0 s | 21.7 fps | 1 | 576 ms |
| 4.1 s | 20 to 30 fps | 0 | 64 ms |

**WinUSB has a ceiling.** It registers its isochronous buffers up front and
only tolerates about 1024 packets in flight. Past that, cancelling the queue
doesn't fail cleanly: it crashes inside libusb and the Python process dies on
`_PyThreadState_Attach`. `MAX_QUEUED_PACKETS` keeps every configuration on the
safe side of that limit.

WinUSB doesn't need the depth anyway: it's steady from 0.5 s, with no gaps and
48 ms at worst. So the driver the app installs is also the one these settings
suit.

## License

**GPL-2.0.** The register tables and init sequences are ported from the Linux
**gspca** driver (`drivers/media/usb/gspca/ov519.c`), itself GPL-2.0, which
makes this project a derivative work. The reference copy and the deliberate
deviations from it are in [`reference/`](reference/SOURCE.md).

`vendor/wdi-simple.exe` is **LGPL-3.0**, which isn't compatible with
GPL-2.0-only *when linked*. So it ships as a **separate program**, run as a
subprocess and never linked to this code, which is plain aggregation. That's
also why the app doesn't use `libwdi.dll`. Exact source and patches are in
[`vendor/README.md`](vendor/README.md).

## Roadmap

- [x] USB access, bridge and sensor init, isochronous stream
- [x] Live preview, snapshots, sensor controls
- [x] Digital zoom and panning
- [x] MJPEG AVI recording
- [x] Standalone executable
- [x] One-click driver install, with a signature-checked manual fallback
- [x] Virtual camera, with one-click install of its backend
- [x] Driver and certificate removal from the app
- [x] Automatic alt setting fallback on a busy bus
- [x] Persistent settings, logging, high-DPI display, icon
- [x] English and French interface, settings menu
- [ ] Test the virtual camera end to end in Discord and OBS
- [ ] Capture the built-in microphone, and mux audio with video
- [ ] Signed binary (`build.ps1` supports it, a certificate is needed)

## Tools

| Script | Purpose |
|---|---|
| `tools/probe.py` | dump the USB descriptors |
| `tools/regtest.py` | test access to the bridge registers |
| `tools/detect.py` | init, I²C sync, sensor identification, LED blink |
| `tools/grab.py` | 3 s capture, stats, JPEG marker analysis |
| `tools/snapshot.py` | capture and decode to PNG |
| `tools/test_avi.py` | record an AVI, then parse it back byte by byte |
| `tools/make_icon.py` | draw the icon and write `assets/eyetoy.ico` |

The app also has a self-test mode, which is the only way to check a windowed
build since it has no console:

```powershell
$env:EYETOY_SMOKE = "report.json"; $env:EYETOY_SMOKE_SECONDS = "10"
.\dist\EyeToyStudio.exe
```

It runs for the requested time, records a video, tests the zoom, writes a JSON
health report and exits, without touching your saved settings.
`EYETOY_CAPTURES` sends captures somewhere other than Pictures, and
`EYETOY_UI_SCALE=1.5` simulates a 150% display to check the layout.
