"""EyeToy Studio - a live viewer for the PlayStation 2 EyeToy on Windows.

Run with:  .venv\\Scripts\\python.exe app.py
"""

from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import pathlib
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from eyetoy import (__version__, applog, i18n, paths, settings, setup_driver,
                    vcam)
from eyetoy.i18n import t
from eyetoy.ov519 import Status
from eyetoy.session import CameraSession
from eyetoy.view import MAX_ZOOM, MIN_ZOOM, crop_box

log = logging.getLogger("eyetoy.app")

# Stream modes by settings key; their labels are "mode.<key>" in the catalogue.
# VGA is capped near 14-20 fps by the USB 1.1 bus no matter what the sensor is
# asked for, so it still requests 30: asking for 15 engages the sensor clock
# divider and halves an already bus-limited stream.
MODES = {
    "qvga30": (320, 240, 30),
    "qvga15": (320, 240, 15),
    "vga": (640, 480, 30),
}

# Preview size at 100 % display scaling; scaled up with the system DPI.
BASE_VIEW_W, BASE_VIEW_H = 640, 480

BG = "#16171b"
PANEL = "#212329"
FG = "#e6e6e6"
MUTED = "#8b8f99"
WARN = "#ffb454"
REC = "#ff5f56"


def enable_dpi_awareness() -> None:
    """Draw at the display's real resolution instead of being bitmap-stretched.

    Without this, Windows scales the whole window as an image at 125 % or
    150 %, which blurs text and the preview alike. System-aware is the level
    Tk handles: it reads the DPI once at startup and sizes fonts from it.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class App:
    def __init__(self, root: tk.Tk, *, persist: bool = True,
                 log_path: pathlib.Path | None = None):
        self.root = root
        self.persist = persist
        self.log_path = log_path
        self.prefs = settings.load()
        # Before anything produces text, worker threads included.
        i18n.set_language(str(self.prefs["language"]))

        self.session = CameraSession(*MODES[str(self.prefs["mode"])])
        self.session.start()
        self.vcam = vcam.VirtualCamera()
        self.captures = paths.captures_dir(str(self.prefs["captures_dir"]))

        self._photo: ImageTk.PhotoImage | None = None
        self._view_image: Image.Image | None = None
        self._last_seq = -1
        self._last_button = False
        self._toast = ""
        self._message: str | None = None
        self._closing = False
        self._record_started = 0.0
        # What the UI believes, so a recording the session dropped on its own
        # (a full disk) is noticed and the controls put back.
        self._ui_recording = False
        self._last_error_toast = 0.0

        # Digital zoom: a crop factor plus the crop centre in normalised
        # coordinates, so panning survives a resolution change.
        self.zoom = 1.0
        self.center = [0.5, 0.5]
        self._drag_from: tuple[int, int] | None = None

        self._size_for_display()

        root.title(f"EyeToy Studio {__version__}")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.report_callback_exception = self._on_tk_error

        self._build_style()
        self._build_menu()
        self._build_layout()

        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<space>", lambda _e: self.snapshot())
        root.bind("<Escape>", lambda _e: self.quit())
        root.bind("<KeyPress-r>", lambda _e: self.toggle_record())
        root.bind("<KeyPress-0>", lambda _e: self.reset_view())
        self._tick()

    # -- sizing -------------------------------------------------------------
    def _size_for_display(self) -> None:
        """Scale the preview with the display, without outgrowing the screen.

        EYETOY_UI_SCALE forces a factor, to check a layout at 150 % from a
        100 % display, or to enlarge the window by hand.
        """
        try:
            forced = float(os.environ.get("EYETOY_UI_SCALE", ""))
        except ValueError:
            forced = 0.0
        self.scale = max(1.0, forced or self.root.winfo_fpixels("1i") / 96.0)
        if forced:
            # Fonts are sized in points; make Tk convert them at the same rate.
            self.root.tk.call("tk", "scaling", forced * 96.0 / 72.0)
        fit = min(self.scale,
                  self.root.winfo_screenwidth() * 0.62 / BASE_VIEW_W,
                  self.root.winfo_screenheight() * 0.72 / BASE_VIEW_H)
        self.view_w = max(BASE_VIEW_W, round(BASE_VIEW_W * fit / 4) * 4)
        self.view_h = self.view_w * BASE_VIEW_H // BASE_VIEW_W

    def px(self, value: float) -> int:
        """A length given at 100 % scaling, in physical pixels."""
        return round(value * self.scale)

    # -- UI construction ----------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=FG,
                        fieldbackground=PANEL, borderwidth=0)
        style.configure("TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=FG)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Warn.TLabel", background=PANEL, foreground=WARN)
        style.configure("Title.TLabel", background=PANEL, foreground=MUTED,
                        font=("Segoe UI", 8, "bold"))
        style.configure("TButton", background="#31343c", foreground=FG,
                        padding=self.px(6))
        style.map("TButton", background=[("active", "#3d414b")])
        style.configure("Small.TButton", background="#2a2d34", foreground=MUTED,
                        padding=self.px(3), font=("Segoe UI", 8))
        style.map("Small.TButton", background=[("active", "#3d414b")])
        style.configure("Rec.TButton", background="#5a2b2b", foreground="#ffd9d7")
        style.map("Rec.TButton", background=[("active", "#6d3434")])
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TScale", background=PANEL, troughcolor="#31343c")
        style.configure("TCombobox", fieldbackground="#31343c",
                        background="#31343c", foreground=FG, arrowcolor=FG)
        # clam paints a read-only combobox with its own light field colour,
        # which left the light text unreadable: pin every state to the theme.
        style.map("TCombobox",
                  fieldbackground=[("readonly", "#31343c"),
                                   ("disabled", "#26282e")],
                  foreground=[("disabled", MUTED), ("readonly", FG)],
                  background=[("active", "#3d414b"), ("readonly", "#31343c")],
                  selectbackground=[("readonly", "#31343c")],
                  selectforeground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", "#2a2d34")
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#3d414b")
        self.root.option_add("*TCombobox*Listbox.selectForeground", FG)
        style.map("TScale", troughcolor=[("disabled", "#26282e")])

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        settings_menu = tk.Menu(menubar, tearoff=False)
        language_menu = tk.Menu(settings_menu, tearoff=False)
        self.language_var = tk.StringVar(value=i18n.language())
        for code, name in i18n.LANGUAGES.items():
            language_menu.add_radiobutton(
                label=name, value=code, variable=self.language_var,
                command=lambda: self.set_language(self.language_var.get()))
        settings_menu.add_cascade(label=t("menu.language"), menu=language_menu)
        settings_menu.add_separator()
        settings_menu.add_command(label=t("menu.captures_dir"),
                                  command=self.choose_captures)
        settings_menu.add_command(label=t("menu.captures_default"),
                                  command=self.default_captures)
        settings_menu.add_command(label=t("menu.open_captures"),
                                  command=self.open_captures)
        settings_menu.add_separator()
        settings_menu.add_command(label=t("menu.reset_image"),
                                  command=self.reset_image_settings)
        settings_menu.add_command(label=t("menu.driver"),
                                  command=self._show_driver_dialog)
        menubar.add_cascade(label=t("menu.settings"), menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label=t("menu.open_log"), command=self.open_log)
        help_menu.add_separator()
        help_menu.add_command(label=t("menu.about"), command=self.show_about)
        menubar.add_cascade(label=t("menu.help"), menu=help_menu)

        self.root.configure(menu=menubar)

    def _build_layout(self) -> None:
        px = self.px
        width = px(200)
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=px(10), pady=px(10))

        vw, vh = self.view_w, self.view_h
        self.canvas = tk.Canvas(body, width=vw, height=vh, bg="#000000",
                                highlightthickness=1,
                                highlightbackground="#2c2f36", cursor="fleur")
        self.canvas.pack(side="left", anchor="n")
        self._image_id = self.canvas.create_image(vw // 2, vh // 2)
        self._message_id = self.canvas.create_text(
            vw // 2, vh // 2, text=t("overlay.connecting"), fill=MUTED,
            width=vw - px(80), justify="center", font=("Segoe UI", 11))
        self._zoom_id = self.canvas.create_text(
            px(12), px(12), text="", fill="#ffffff", anchor="nw",
            font=("Consolas", 9, "bold"))
        self._rec_id = self.canvas.create_text(
            vw - px(12), px(12), text="", fill=REC, anchor="ne",
            font=("Consolas", 9, "bold"))
        self._toast_id = self.canvas.create_text(
            vw // 2, vh - px(26), text="", fill="#ffffff", width=vw - px(40),
            justify="center", font=("Segoe UI", 10, "bold"))

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.reset_view())

        panel = ttk.Frame(body, padding=px(12))
        panel.pack(side="left", fill="y", padx=(px(10), 0))

        ttk.Label(panel, text=t("panel.stream"), style="Title.TLabel").pack(
            anchor="w")
        self._mode_keys = list(MODES)
        self.mode_box = ttk.Combobox(
            panel, width=20, state="readonly",
            values=[t(f"mode.{key}") for key in self._mode_keys])
        self.mode_box.current(self._mode_keys.index(self._mode_key()))
        self.mode_box.pack(anchor="w", pady=(px(4), px(10)))
        self.mode_box.bind("<<ComboboxSelected>>", self._on_mode)

        ttk.Label(panel, text=t("panel.zoom"), style="Title.TLabel").pack(
            anchor="w")
        zoom_row = ttk.Frame(panel)
        zoom_row.pack(fill="x", pady=(px(4), 0))
        ttk.Label(zoom_row, text=t("panel.zoom_hint"), style="Muted.TLabel",
                  font=("Segoe UI", 8)).pack(side="left")
        self.zoom_label = ttk.Label(zoom_row, text="1.0x", style="Muted.TLabel",
                                    font=("Consolas", 8))
        self.zoom_label.pack(side="right")
        self.zoom_var = tk.DoubleVar(value=self.zoom)
        ttk.Scale(panel, from_=MIN_ZOOM, to=MAX_ZOOM, variable=self.zoom_var,
                  command=self._on_zoom_slider, orient="horizontal",
                  length=width).pack(fill="x")
        ttk.Button(panel, text=t("panel.reset_view"),
                   command=self.reset_view).pack(fill="x", pady=(px(6), px(10)))

        ttk.Label(panel, text=t("panel.image"), style="Title.TLabel").pack(
            anchor="w")
        self._scales: dict[str, ttk.Scale] = {}
        self._sliders = {
            "brightness": self._slider(panel, "brightness"),
            "exposure": self._slider(panel, "exposure"),
            "saturation": self._slider(panel, "saturation"),
        }

        self.autogain_var = tk.BooleanVar(value=bool(self.prefs["autogain"]))
        ttk.Checkbutton(panel, text=t("control.autogain"),
                        variable=self.autogain_var,
                        command=self._on_autogain).pack(anchor="w",
                                                        pady=(px(8), 0))
        # Push the shown values to the sensor, so what the panel says is what
        # the camera does, from the first frame and after every reconnect.
        self._on_autogain()
        self.mirror_var = tk.BooleanVar(value=bool(self.prefs["mirror"]))
        ttk.Checkbutton(panel, text=t("control.mirror"),
                        variable=self.mirror_var).pack(anchor="w")
        self.smooth_var = tk.BooleanVar(value=bool(self.prefs["smooth"]))
        ttk.Checkbutton(panel, text=t("control.smooth"),
                        variable=self.smooth_var).pack(anchor="w")

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=px(10))

        ttk.Button(panel, text=t("action.photo"),
                   command=self.snapshot).pack(fill="x")
        self.record_button = ttk.Button(panel, text=t("action.record"),
                                        command=self.toggle_record)
        self.record_button.pack(fill="x", pady=(px(6), 0))
        ttk.Button(panel, text=t("action.open_captures"),
                   style="Small.TButton",
                   command=self.open_captures).pack(fill="x", pady=(px(6), 0))

        self.vcam_var = tk.BooleanVar(value=False)
        self.vcam_check = ttk.Checkbutton(panel, text=t("vcam.check"),
                                          variable=self.vcam_var,
                                          command=self._on_vcam)
        self.vcam_check.pack(anchor="w", pady=(px(10), 0))
        self.vcam_label = ttk.Label(panel, text="", style="Muted.TLabel",
                                    font=("Segoe UI", 8), wraplength=width,
                                    justify="left")
        self.vcam_label.pack(anchor="w")
        self.vcam_install = ttk.Button(panel, text=t("vcam.install_button"),
                                       command=self._install_vcam)

        # Shown only while the camera has no usable driver.
        self.fix_button = ttk.Button(panel, text=t("driver.install_button"),
                                     command=self._show_driver_dialog)

        ttk.Frame(panel).pack(fill="both", expand=True)
        self.status = ttk.Label(panel, text="", style="Muted.TLabel",
                                font=("Consolas", 8), justify="left")
        self.status.pack(anchor="w")
        ttk.Button(panel, text=t("panel.driver"), style="Small.TButton",
                   command=self._show_driver_dialog).pack(anchor="w",
                                                          pady=(px(6), 0))

    def _slider(self, parent, control: str) -> tk.IntVar:
        value = int(self.prefs[control])
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(self.px(5), 0))
        ttk.Label(row, text=t(f"control.{control}"),
                  font=("Segoe UI", 9)).pack(side="left")
        value_label = ttk.Label(row, text=str(value), style="Muted.TLabel",
                                font=("Consolas", 8))
        value_label.pack(side="right")
        var = tk.IntVar(value=value)

        def on_move(_value):
            value_label.configure(text=str(var.get()))
            self.session.set_control(control, var.get())

        scale = ttk.Scale(parent, from_=0, to=255, variable=var,
                          command=on_move, orient="horizontal",
                          length=self.px(200))
        scale.pack(fill="x")
        self._scales[control] = scale
        self.session.set_control(control, value)
        return var

    def _rebuild_ui(self) -> None:
        """Recreate menu and window contents, after a language change or a
        settings reset. Camera, recording, zoom and virtual camera carry on."""
        vcam_on = self.vcam_var.get()
        for child in self.root.winfo_children():
            child.destroy()
        self._photo = None
        self._message = None
        self._last_seq = -1             # repaint the current frame at once
        self._build_menu()
        self._build_layout()
        self._set_zoom(self.zoom)
        if vcam_on:
            self.vcam_var.set(True)
            if self.vcam.device:
                self.vcam_label.configure(
                    text=t("vcam.device", device=self.vcam.device))
        if self._ui_recording:
            self._show_recording_controls()

    # -- settings -----------------------------------------------------------
    def _current_prefs(self) -> dict[str, object]:
        return {
            **self.prefs,
            "language": i18n.language(),
            "mode": self._mode_key(),
            **{name: var.get() for name, var in self._sliders.items()},
            "autogain": self.autogain_var.get(),
            "mirror": self.mirror_var.get(),
            "smooth": self.smooth_var.get(),
        }

    def save_settings(self) -> None:
        if self.persist:
            settings.save(self._current_prefs())

    def set_language(self, code: str) -> None:
        if code == i18n.language():
            return
        self.prefs = self._current_prefs()
        i18n.set_language(code)
        self.prefs["language"] = i18n.language()
        log.info("language set to %s", i18n.language())
        self._rebuild_ui()
        self.save_settings()

    def reset_image_settings(self) -> None:
        self.prefs = self._current_prefs()
        for key in settings.IMAGE_KEYS:
            self.prefs[key] = settings.DEFAULTS[key]
        self._rebuild_ui()
        self.save_settings()
        self._show_toast(t("toast.settings_reset"))

    def choose_captures(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.root, title=t("dialog.choose_captures"),
            initialdir=str(self.captures if self.captures.is_dir()
                           else pathlib.Path.home()), mustexist=False)
        if chosen:
            self._set_captures(str(pathlib.Path(chosen)))

    def default_captures(self) -> None:
        self._set_captures("")

    def _set_captures(self, chosen: str) -> None:
        self.prefs["captures_dir"] = chosen
        self.captures = paths.captures_dir(chosen)
        self.save_settings()
        self._show_toast(t("toast.captures_dir", path=self.captures))

    # -- zoom and pan -------------------------------------------------------
    def _set_zoom(self, value: float) -> None:
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, value))
        if abs(self.zoom_var.get() - self.zoom) > 1e-3:
            self.zoom_var.set(self.zoom)
        self.zoom_label.configure(text=f"{self.zoom:.1f}x")
        self.canvas.itemconfigure(
            self._zoom_id, text="" if self.zoom <= 1.001 else f"{self.zoom:.1f}x")

    def _on_zoom_slider(self, _value) -> None:
        self._set_zoom(self.zoom_var.get())

    def _on_wheel(self, event) -> None:
        self._set_zoom(self.zoom * (1.15 if event.delta > 0 else 1 / 1.15))

    def _on_press(self, event) -> None:
        self._drag_from = (event.x, event.y)

    def _on_drag(self, event) -> None:
        if self._drag_from is None or self._view_image is None:
            return
        dx, dy = event.x - self._drag_from[0], event.y - self._drag_from[1]
        self._drag_from = (event.x, event.y)
        # Convert screen pixels to a shift of the normalised crop centre.
        self.center[0] -= dx / (self.view_w * self.zoom)
        self.center[1] -= dy / (self.view_h * self.zoom)
        self.center[0] = min(1.0, max(0.0, self.center[0]))
        self.center[1] = min(1.0, max(0.0, self.center[1]))

    def reset_view(self) -> None:
        self.center = [0.5, 0.5]
        self._set_zoom(1.0)

    # -- actions ------------------------------------------------------------
    def _mode_key(self) -> str:
        for key, mode in MODES.items():
            if mode == self.session.mode:
                return key
        return next(iter(MODES))

    def _on_mode(self, _event=None) -> None:
        if self.session.recording:
            self.mode_box.current(self._mode_keys.index(self._mode_key()))
            self._show_toast(t("toast.stop_recording_first"))
            return
        self.session.set_mode(*MODES[self._mode_keys[self.mode_box.current()]])
        self._show_toast(t("toast.mode_changing"))

    def _on_autogain(self) -> None:
        auto = self.autogain_var.get()
        self.session.set_control("autogain", auto)
        # With automatic exposure on, the sensor overwrites the exposure
        # register itself: the slider would do nothing.
        self._scales["exposure"].state(["disabled"] if auto else ["!disabled"])
        if not auto:
            self.session.set_control("exposure", self._sliders["exposure"].get())

    def _on_vcam(self) -> None:
        if not self.vcam_var.get():
            self.vcam.close()
            self.vcam_label.configure(text="")
            self.vcam_install.pack_forget()
            return

        ok, message = vcam.availability()
        self.vcam_label.configure(text=message)
        if ok:
            self.vcam_install.pack_forget()
            self._show_toast(t("toast.vcam_visible"))
            return

        # Windows has no virtual video device of its own, and an unsigned,
        # unpackaged app cannot register one. OBS Studio ships the one that is
        # signed, free and installable unattended, so offer to fetch it.
        self.vcam_var.set(False)
        if vcam.can_install():
            self.vcam_label.configure(text=f"{message}\n\n{t('vcam.obs_needed')}")
            self.vcam_install.pack(fill="x", pady=(self.px(6), 0),
                                   after=self.vcam_label)
        else:
            self._show_toast(t("toast.vcam_unavailable"))

    def _install_vcam(self) -> None:
        self.vcam_install.configure(state="disabled")

        def report(message: str) -> None:
            if self.vcam_label.winfo_exists():
                self.vcam_label.configure(text=message)

        def done(ok) -> None:
            if not self.vcam_install.winfo_exists():
                return
            if ok:
                self.vcam_install.pack_forget()
                self.vcam_var.set(True)
                self._show_toast(t("toast.vcam_ready"))
            else:
                self.vcam_install.configure(state="normal")

        self._run_task(vcam.install_backend, report, done)

    def _capture_path(self, suffix: str, millis: bool) -> pathlib.Path:
        self.captures.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        stamp = stamp[:-3] if millis else stamp[:15]
        return self.captures / f"eyetoy_{stamp}.{suffix}"

    def snapshot(self) -> None:
        if self._view_image is None:
            self._show_toast(t("toast.no_image"))
            return
        try:
            path = self._capture_path("png", millis=True)
            self._view_image.save(path)
        except OSError as exc:
            log.error("photo not saved: %s", exc)
            self._show_toast(t("toast.photo_failed", error=exc.strerror or exc))
            return
        self._show_toast(t("toast.photo_saved", name=path.name))

    def toggle_record(self) -> None:
        if self.session.recording:
            summary = self.session.stop_recording()
            self._recording_stopped()
            if summary:
                self._show_toast(t(
                    "toast.recorded", name=summary["path"].name,
                    frames=summary["frames"], fps=summary["fps"],
                    mb=summary["bytes"] / 1024 / 1024))
            return
        if not self.session.connected:
            self._show_toast(t("toast.not_connected"))
            return
        try:
            self.session.start_recording(self._capture_path("avi", millis=False))
        except OSError as exc:
            log.error("cannot start recording: %s", exc)
            self._show_toast(t("toast.record_failed", error=exc.strerror or exc))
            return
        self._ui_recording = True
        self._record_started = time.monotonic()
        self._show_recording_controls()

    def _show_recording_controls(self) -> None:
        self.record_button.configure(text=t("action.stop"), style="Rec.TButton")
        self.mode_box.configure(state="disabled")

    def _recording_stopped(self) -> None:
        self._ui_recording = False
        self.record_button.configure(text=t("action.record"), style="TButton")
        self.mode_box.configure(state="readonly")
        self.canvas.itemconfigure(self._rec_id, text="")

    def _open(self, path: pathlib.Path, make_dir: bool = False) -> None:
        try:
            if make_dir:
                path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except OSError as exc:
            self._show_toast(t("toast.folder_failed", error=exc.strerror or exc))

    def open_captures(self) -> None:
        self._open(self.captures, make_dir=True)

    def open_log(self) -> None:
        if self.log_path is None or not self.log_path.is_file():
            self._show_toast(t("toast.no_log"))
            return
        self._open(self.log_path)

    def show_about(self) -> None:
        messagebox.showinfo(
            t("about.title"),
            t("about.text", version=__version__, captures=self.captures,
              log=self.log_path or "-"),
            parent=self.root)

    def _run_task(self, work, report, done=None) -> None:
        """Run a blocking job off the Tk thread, funnelling messages back.

        ``done`` is called on the Tk thread once the job is over, with the
        job's return value, or None if it raised.
        """
        def deliver(message: str) -> None:
            if not self._closing:
                self.root.after(0, report, message)

        def runner() -> None:
            result = None
            try:
                result = work(deliver)
            except Exception as exc:                # noqa: BLE001 - shown in UI
                log.exception("background task")
                deliver(f"{type(exc).__name__}: {exc}")
            finally:
                if done is not None and not self._closing:
                    self.root.after(0, done, result)

        threading.Thread(target=runner, daemon=True).start()

    def _show_driver_dialog(self) -> None:
        """Install, repair or remove the driver binding of the video interface.

        Binding a generic driver to a device needs an INF whose catalogue is
        signed by a trusted certificate. The automatic route generates and
        trusts one behind a single UAC prompt; the manual route hands over to
        the official, signature-checked Zadig.
        """
        window = tk.Toplevel(self.root)
        window.title(t("driver.title"))
        window.configure(bg=PANEL)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        wrap = self.px(440)

        frame = ttk.Frame(window, padding=self.px(16))
        frame.pack(fill="both", expand=True)

        missing = self.session.status is Status.DRIVER_MISSING
        ttk.Label(frame, text=t("driver.headline_missing" if missing
                                else "driver.headline"),
                  style="Warn.TLabel" if missing else "TLabel",
                  wraplength=wrap,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(frame, text=t("driver.intro"), style="Muted.TLabel",
                  wraplength=wrap, justify="left").pack(
            anchor="w", pady=(self.px(8), self.px(12)))

        ttk.Label(frame, text=t("driver.what"),
                  style="Title.TLabel").pack(anchor="w")
        for key in ("driver.detail_bind", "driver.detail_cert",
                    "driver.detail_mic"):
            ttk.Label(frame, text=f"•  {t(key)}", style="Muted.TLabel",
                      font=("Segoe UI", 8), wraplength=wrap,
                      justify="left").pack(anchor="w", pady=(self.px(2), 0))

        progress = ttk.Label(frame, text="", wraplength=wrap, justify="left",
                             font=("Consolas", 8))
        progress.pack(anchor="w", pady=(self.px(12), 0))

        manual = ttk.Label(frame, text="", style="Muted.TLabel",
                           wraplength=wrap, justify="left",
                           font=("Consolas", 8))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(self.px(14), 0))
        auto = ttk.Button(buttons, text=t("driver.install"))
        auto.pack(side="left")
        fallback = ttk.Button(buttons, text=t("driver.manual"))
        fallback.pack(side="left", padx=(self.px(8), 0))
        remove = ttk.Button(buttons, text=t("driver.uninstall"))
        remove.pack(side="left", padx=(self.px(8), 0))
        ttk.Button(buttons, text=t("driver.close"),
                   command=window.destroy).pack(side="right")
        actions = (auto, fallback, remove)

        def busy(on: bool) -> None:
            for button in actions:
                if button.winfo_exists():
                    button.configure(state="disabled" if on else "normal")

        def report(message: str) -> None:
            if progress.winfo_exists():
                progress.configure(text=message)

        def idle(_result) -> None:
            busy(False)

        def installed(result) -> None:
            busy(False)
            if result:
                self._show_toast(t("toast.driver_installed"))

        def begin_auto() -> None:
            busy(True)
            self._run_task(setup_driver.install_winusb, report, installed)

        def begin_manual() -> None:
            busy(True)
            manual.pack(anchor="w", pady=(self.px(10), 0))
            manual.configure(text=t("driver.zadig_steps"))
            self._run_task(setup_driver.install_with_zadig, report, idle)

        def begin_remove() -> None:
            if not messagebox.askyesno(t("driver.confirm_title"),
                                       t("driver.confirm"), parent=window):
                return
            busy(True)
            self._run_task(setup_driver.uninstall_driver, report, idle)

        auto.configure(command=begin_auto)
        fallback.configure(command=begin_manual)
        remove.configure(command=begin_remove)

    def _show_toast(self, text: str) -> None:
        self._toast = text
        self.canvas.itemconfigure(self._toast_id, text=text)
        self.root.after(3500, self._clear_toast, text)

    def _clear_toast(self, text: str) -> None:
        if self._closing or self._toast != text:
            return
        self._toast = ""
        self.canvas.itemconfigure(self._toast_id, text="")

    def _on_tk_error(self, kind, value, tb) -> None:
        """Tk swallows callback exceptions: log them and say so on screen."""
        log.error("error in the UI", exc_info=(kind, value, tb))
        now = time.monotonic()
        if not self._closing and now - self._last_error_toast > 5:
            self._last_error_toast = now
            self._show_toast(t("toast.unexpected_error", error=value))

    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.save_settings()
        self.session.stop_recording()
        self.session.close()
        self.vcam.close()
        self.root.destroy()

    # -- render loop --------------------------------------------------------
    def _tick(self) -> None:
        if self._closing:
            return
        seq, jpeg = self.session.latest()
        if jpeg is not None and seq != self._last_seq:
            self._last_seq = seq
            self._render(jpeg)

        # The camera's own button fires a snapshot on the press edge.
        if self.session.button and not self._last_button:
            self.snapshot()
        self._last_button = self.session.button

        self._update_status()
        self.root.after(10, self._tick)

    def _crop(self, image: Image.Image) -> Image.Image:
        box = crop_box(image.width, image.height, self.zoom,
                       (self.center[0], self.center[1]))
        return image if box is None else image.crop(box)

    def _zoom_selftest(self) -> bool:
        """Check the crop maths stays inside the frame at every extreme."""
        width, height, _ = self.session.mode
        for zoom in (1.0, 1.5, 3.0, MAX_ZOOM):
            for center in ((0.5, 0.5), (0.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
                box = crop_box(width, height, zoom, center) or (0, 0, width,
                                                                 height)
                left, top, right, bottom = box
                if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                    return False
        return True

    def _render(self, jpeg: bytes) -> None:
        try:
            image = Image.open(io.BytesIO(jpeg))
            image.load()
        except OSError:
            return  # a torn frame; the next one will be along in ~33 ms
        if self.mirror_var.get():
            image = ImageOps.mirror(image)

        native = image.size
        view = self._crop(image)
        self._view_image = view

        resample = Image.BILINEAR if self.smooth_var.get() else Image.NEAREST
        size = (self.view_w, self.view_h)
        shown = view if view.size == size else view.resize(size, resample)
        if self._photo is None:
            self._photo = ImageTk.PhotoImage(shown)
            self.canvas.itemconfigure(self._image_id, image=self._photo)
        else:
            # Repainting the existing Tk image avoids allocating and destroying
            # a PhotoImage thirty times a second.
            self._photo.paste(shown)
        self._set_message("")

        if self.vcam_var.get():
            # Publish at the sensor's native size whatever the zoom, so the
            # virtual device does not change resolution under its consumers.
            output = view if view.size == native else view.resize(native,
                                                                  resample)
            self.vcam.send(output, self.session.fps or 30)
            if self.vcam.error:
                self.vcam_label.configure(text=self.vcam.error)

    def _set_message(self, text: str) -> None:
        """Update the overlay only when it actually changes."""
        if text != self._message:
            self._message = text
            self.canvas.itemconfigure(self._message_id, text=text)

    def _update_status(self) -> None:
        session = self.session
        if not session.connected:
            self._set_message(session.error or session.status_detail
                              or t("overlay.searching"))
            self._view_image = None
        if session.status is Status.DRIVER_MISSING and not session.connected:
            if not self.fix_button.winfo_ismapped():
                self.fix_button.pack(fill="x", pady=(self.px(10), 0),
                                     before=self.vcam_check)
        elif self.fix_button.winfo_ismapped():
            self.fix_button.pack_forget()

        if self._ui_recording and not session.recording:
            # The session dropped the recording on its own, on a write error.
            self._recording_stopped()
            self._show_toast(session.recording_error
                             or t("toast.recording_stopped"))
        if session.recording:
            elapsed = int(time.monotonic() - self._record_started)
            self.canvas.itemconfigure(self._rec_id, text=t(
                "status.rec", minutes=elapsed // 60, seconds=elapsed % 60,
                frames=session.recorded_frames))

        stats = session.stats
        width, height, _ = session.mode
        link = session.link
        self.status.configure(text="\n".join([
            f"{session.sensor or '-'}  "
            f"{t('status.up') if session.connected else t('status.down')}",
            t("status.rate", width=width, height=height, fps=session.fps),
            t("status.frames", frames=stats.get("frames", 0),
              dropped=stats.get("discarded", 0)),
            t("status.iso", errors=stats.get("iso_errors", 0))
            + (f"  {t('status.link', alt=link[0], size=link[1])}"
               if link else ""),
        ]))


def set_window_icon(root: tk.Tk) -> bool:
    icon = paths.resource("assets", "eyetoy.ico")
    try:
        # default= applies to every later Toplevel too.
        root.iconbitmap(default=str(icon))
        return True
    except tk.TclError as exc:
        log.warning("icon not loaded (%s): %s", icon, exc)
        return False


def main() -> int:
    log_path = applog.setup()
    log.info("EyeToy Studio %s starting (python %s, %s)", __version__,
             sys.version.split()[0],
             "frozen" if getattr(sys, "frozen", False) else "source")
    enable_dpi_awareness()
    root = tk.Tk()
    icon_ok = set_window_icon(root)

    # Set EYETOY_SMOKE to a path to run headlessly for a few seconds and drop a
    # JSON health report there. This is the only way to check a --windowed
    # build, which has no console to print to.
    smoke = os.environ.get("EYETOY_SMOKE")
    app = App(root, persist=not smoke, log_path=log_path)

    if smoke:
        def finish() -> None:
            session = app.session
            summary = session.stop_recording()
            pathlib.Path(smoke).write_text(json.dumps({
                "connected": session.connected,
                "sensor": session.sensor,
                "link": None if not session.link else
                        {"alt": session.link[0], "packet": session.link[1]},
                "fps": round(session.fps, 1),
                "error": session.error,
                "stats": dict(session.stats),
                "frames_rendered": app._last_seq,
                "recording": None if not summary else {
                    "frames": summary["frames"],
                    "fps": round(summary["fps"], 1),
                    "bytes": summary["bytes"]},
                "zoom_ok": app._zoom_selftest(),
                "vcam": vcam.availability()[1],
                "driver_installer": str(setup_driver.wdi_simple_path()),
                "icon": icon_ok,
                "language": i18n.language(),
                "dpi_scale": round(app.scale, 2),
                "view": [app.view_w, app.view_h],
                "captures": str(app.captures),
                "log": str(log_path),
                "frozen": getattr(sys, "frozen", False),
                "version": __version__,
            }, indent=2), encoding="utf-8")
            app.quit()

        root.after(2500, app.toggle_record)
        root.after(int(os.environ.get("EYETOY_SMOKE_SECONDS", "8")) * 1000,
                   finish)

    root.mainloop()
    log.info("EyeToy Studio closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
