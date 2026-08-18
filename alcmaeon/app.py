"""
Alcmaeon Lite -- main window
============================

Layout
------
    +------------------------------------------------------------+
    |  alcmaeon                                                   |
    +---------------------+--------------------------------------+
    |  control column     |  figure: white line-art backdrop,     |
    |  (rounded cards)    |  translucent graph panels on top      |
    +---------------------+--------------------------------------+
    |  status line                                                |
    +------------------------------------------------------------+

Data flow
---------
    source thread -> queue -> _poll() -> filter chains -> ring buffer
                                                       -> recorder (if armed)
    _redraw() reads the ring buffer at PLOT_FPS and updates the lines.

Named after Alcmaeon of Croton, who argued the brain -- not the heart -- is
the seat of sensation.
"""

from __future__ import annotations

import math
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from . import analysis
from . import artwork
from . import config as cfg
from . import filters as flt
from . import loader
from . import recorder as rec
from . import settings
from .acquisition import SIMULATOR_NAME, Sample, available_ports, make_source
from .buffers import RingBuffer, decimate
from .theme import (FONTS, PALETTE, RoundedButton, RoundedPanel, Toggle,
                    apply_theme, legend_kwargs, style_axes, trace_color)


MARKER_COLOR = "#C9A227"     # markers: ochre, distinct from art and traces
EVENT_COLOR = PALETTE["warn"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ScrollableFrame(ttk.Frame):
    """Vertically scrolling container -- the control column outgrows short screens."""

    def __init__(self, master, width: int = 336, **kw):
        super().__init__(master, style="Page.TFrame", **kw)
        self.canvas = tk.Canvas(self, bg=PALETTE["bg"], highlightthickness=0,
                                bd=0, width=width)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Page.TFrame")

        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


def field(parent, text: str, var: tk.Variable, row: int, width: int = 8,
          suffix: str = "") -> None:
    """One `label [entry] unit` line in a grid."""
    ttk.Label(parent, text=text, style="Muted.TLabel").grid(
        row=row, column=0, sticky="w", pady=2)
    ttk.Entry(parent, textvariable=var, width=width, font=FONTS["ui"]).grid(
        row=row, column=1, sticky="e", pady=2)
    ttk.Label(parent, text=suffix or " ", style="Faint.TLabel").grid(
        row=row, column=2, sticky="w", padx=(5, 0))


class ChannelUI:
    """Tk variables + plot handles for one channel."""

    def __init__(self, name: str, index: int, is_digital: bool,
                 default_view: str, color: str, default_filter: str = "Raw"):
        self.name = name
        self.index = index
        self.is_digital = is_digital
        self.color = color
        self.visible = tk.BooleanVar(value=default_view != "hidden")
        self.view = tk.StringVar(value=default_view if default_view != "hidden"
                                 else "own")
        self.filter_name = tk.StringVar(value=default_filter)
        self.chain: flt.FilterChain | None = None

    @property
    def key(self) -> str:
        return f"{'D' if self.is_digital else 'A'}{self.index}"

    @property
    def mode(self) -> str:
        return "hidden" if not self.visible.get() else self.view.get()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class AlcmaeonApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("alcmaeon")
        self.geometry("1320x840")
        self.minsize(1040, 660)
        self.configure(bg=PALETTE["bg"])
        apply_theme(self)

        # --- state ---------------------------------------------------------
        self.sample_queue: queue.Queue[Sample] = queue.Queue(maxsize=200_000)
        self.source = None
        self.recorder = rec.Recorder()

        self.sample_rate = float(cfg.SAMPLE_RATE_HZ)
        self.settings = flt.FilterSettings(
            fs=self.sample_rate,
            highpass_hz=cfg.DEFAULT_HIGHPASS_HZ,
            lowpass_hz=cfg.DEFAULT_LOWPASS_HZ,
            notch_hz=cfg.DEFAULT_NOTCH_HZ,
            notch_q=cfg.DEFAULT_NOTCH_Q,
            envelope_hz=cfg.DEFAULT_ENVELOPE_HZ,
            rms_ms=cfg.DEFAULT_RMS_MS,
            smooth_ms=cfg.DEFAULT_SMOOTH_MS,
        )

        n_columns = 2 * cfg.N_ANALOG + cfg.N_DIGITAL
        self.buffer = RingBuffer(int(cfg.HISTORY_SECONDS * self.sample_rate), n_columns)

        settings.apply_saved()           # a layout set up in the app beats the defaults
        self._build_channel_ui()
        self._rebuild_chains()
        self._saved_layout = None        # set while a file's layout is in use

        self.events: list[tuple[float, str]] = []
        self.mark_a: float | None = None
        self.mark_b: float | None = None

        # Review mode: a loaded file replaces the live buffer until you go back
        self.review: loader.Recording | None = None
        self.live_buffer = self.buffer
        self.view_start: float = 0.0

        self._bg_ax = None
        self._backdrop_name = ""
        self._background = None          # cached bitmap of everything static
        self._background_size = None     # canvas size that bitmap was made for
        self._layout_pending = True      # constrained layout needs a pass
        self._manual_axes: set[str] = set()   # axes the user has scaled by hand
        self._limits = {}                # per-axes y limits currently in force
        self._envelope = {}              # slow-moving signal extent per axes
        self._last_rescale = 0.0
        self._checked_device = False
        self._last_draw = 0.0
        self._rate_marker = (time.time(), 0)
        self._measured_rate = 0.0
        self._total_samples = 0

        # --- widgets -------------------------------------------------------
        self._build_header()
        body = ttk.Frame(self, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        self.controls = ScrollableFrame(body)
        self.controls.pack(side="left", fill="y")
        self._build_plot_area(body)
        self._build_controls(self.controls.inner)
        self._build_statusbar()

        self._rebuild_figure()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(cfg.POLL_MS, self._poll)

    # ------------------------------------------------------------------ UI --

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=PALETTE["bg"], height=58)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        row = tk.Frame(header, bg=PALETTE["bg"])
        row.pack(side="left", padx=20, pady=(16, 0))
        tk.Label(row, text="alcmaeon", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=FONTS["title"]).pack(side="left")
        tk.Label(row, text="\u258e", bg=PALETTE["bg"], fg=PALETTE["blue"],
                 font=FONTS["title"]).pack(side="left", padx=(3, 0))

        tk.Frame(self, bg=PALETTE["line"], height=1).pack(fill="x")

    def _build_plot_area(self, parent) -> None:
        frame = tk.Frame(parent, bg=PALETTE["bg"])
        frame.pack(side="left", fill="both", expand=True, padx=(4, 12), pady=(10, 4))
        self.figure = Figure(figsize=(8, 6), dpi=100,
                             facecolor=PALETTE["bg"], layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        widget = self.canvas.get_tk_widget()
        widget.configure(bg=PALETTE["bg"], highlightthickness=0, bd=0)
        widget.pack(fill="both", expand=True)
        self.canvas.mpl_connect("button_press_event", self._on_plot_click)
        self.canvas.mpl_connect("scroll_event", self._on_plot_scroll)
        # add="+" is essential: a plain bind would replace matplotlib's own
        # <Configure> handler and the figure would never resize with the window
        widget.bind("<Configure>", lambda e: self._invalidate_background(True), add="+")

    def _invalidate_background(self, relayout: bool = False) -> None:
        """Force the static layer to be re-rendered on the next frame."""
        self._background = None
        self._background_size = None
        if relayout:
            self._layout_pending = True

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=PALETTE["bg"])
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=PALETTE["line"], height=1).pack(fill="x")
        self.status_var = tk.StringVar(value="idle \u00b7 select a port and connect")
        tk.Label(bar, textvariable=self.status_var, bg=PALETTE["bg"],
                 fg=PALETTE["muted"], font=FONTS["small"], anchor="w").pack(
            fill="x", padx=20, pady=6)

    def _card(self, parent, title: str) -> tk.Frame:
        panel = RoundedPanel(parent, title=title)
        panel.pack(fill="x", padx=12, pady=(10, 0))
        return panel.body

    # --- control column ---------------------------------------------------

    def _build_controls(self, p) -> None:
        # ---- link ---------------------------------------------------------
        box = self._card(p, "link")
        self.port_var = tk.StringVar(value=SIMULATOR_NAME)
        self.port_combo = ttk.Combobox(box, textvariable=self.port_var,
                                       values=available_ports(), state="readonly",
                                       font=FONTS["ui"])
        self.port_combo.pack(fill="x", pady=(0, 6))

        buttons = tk.Frame(box, bg=PALETTE["surface"])
        buttons.pack(fill="x")
        RoundedButton(buttons, "refresh", self._refresh_ports).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        self.connect_btn = RoundedButton(buttons, "connect", self._toggle_connection,
                                         kind="primary")
        self.connect_btn.pack(side="left", fill="x", expand=True)

        grid = tk.Frame(box, bg=PALETTE["surface"])
        grid.pack(fill="x", pady=(8, 0))
        grid.columnconfigure(1, weight=1)
        self.baud_var = tk.IntVar(value=cfg.SERIAL_BAUD)
        self.rate_var = tk.DoubleVar(value=self.sample_rate)
        field(grid, "baud", self.baud_var, 0)
        field(grid, "sample rate", self.rate_var, 1, suffix="hz")
        ttk.Label(box, text="must match the arduino sketch", style="Faint.TLabel").pack(
            anchor="w", pady=(6, 0))

        # ---- open / review saved recordings --------------------------------
        box = self._card(p, "file")
        RoundedButton(box, "open a recording\u2026", self._open_recording).pack(fill="x")
        self.file_label = ttk.Label(box, text="live input", style="Muted.TLabel")
        self.file_label.pack(anchor="w", pady=(6, 0))

        # everything below only appears once a file is open
        self.review_box = tk.Frame(box, bg=PALETTE["surface"])
        self.scrub_var = tk.DoubleVar(value=0.0)
        self.scrub = ttk.Scale(self.review_box, from_=0.0, to=1.0,
                               variable=self.scrub_var, command=self._on_scrub)
        self.scrub.pack(fill="x", pady=(8, 2))
        self.scrub_label = ttk.Label(self.review_box, text="", style="Faint.TLabel")
        self.scrub_label.pack(anchor="w")
        self.fit_var = tk.BooleanVar(value=False)
        Toggle(self.review_box, "fit whole recording", self.fit_var).pack(
            anchor="w", pady=(4, 0))
        self.fit_var.trace_add("write", lambda *_: self._sync_scrub())
        RoundedButton(self.review_box, "back to live input",
                      self._back_to_live).pack(fill="x", pady=(6, 0))

        RoundedButton(box, "analyse\u2026", self._analyse, kind="primary").pack(
            fill="x", pady=(8, 0))
        ttk.Label(box, text="analyses markers a\u2192b if both are set,\n"
                            "otherwise everything loaded",
                  style="Faint.TLabel", justify="left").pack(anchor="w", pady=(6, 0))

        # ---- channels -----------------------------------------------------
        self._channels_box = self._card(p, "channels")
        self._populate_channels()

        # ---- filters ------------------------------------------------------
        box = self._card(p, "filters")
        grid = tk.Frame(box, bg=PALETTE["surface"])
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.hp_var = tk.DoubleVar(value=self.settings.highpass_hz)
        self.lp_var = tk.DoubleVar(value=self.settings.lowpass_hz)
        self.notch_var = tk.DoubleVar(value=self.settings.notch_hz)
        self.q_var = tk.DoubleVar(value=self.settings.notch_q)
        self.env_var = tk.DoubleVar(value=self.settings.envelope_hz)
        self.rms_var = tk.DoubleVar(value=self.settings.rms_ms)
        self.smooth_var = tk.DoubleVar(value=self.settings.smooth_ms)
        field(grid, "high-pass", self.hp_var, 0, suffix="hz")
        field(grid, "low-pass", self.lp_var, 1, suffix="hz")
        field(grid, "notch", self.notch_var, 2, suffix="hz")
        field(grid, "notch q", self.q_var, 3)
        field(grid, "envelope", self.env_var, 4, suffix="hz")
        field(grid, "rms window", self.rms_var, 5, suffix="ms")
        field(grid, "smoothing", self.smooth_var, 6, suffix="ms")
        RoundedButton(box, "apply", self._apply_filter_settings).pack(
            fill="x", pady=(8, 0))

        # ---- view ---------------------------------------------------------
        box = self._card(p, "view")
        row = tk.Frame(box, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="window", style="Muted.TLabel").pack(side="left")
        self.window_var = tk.IntVar(value=cfg.DEFAULT_WINDOW_SECONDS)
        ttk.Combobox(row, textvariable=self.window_var, width=5, state="readonly",
                     values=cfg.WINDOW_CHOICES, font=FONTS["ui"]).pack(side="right")
        self.window_var.trace_add("write", lambda *_: (self._sync_scrub(),
                                                       self._apply_xlimits(),
                                                       self._invalidate_background()))

        self.autoscale_var = tk.BooleanVar(value=True)
        self.show_raw_var = tk.BooleanVar(value=cfg.SHOW_RAW_TRACE)
        self.paused_var = tk.BooleanVar(value=False)
        self.translucent_var = tk.BooleanVar(value=cfg.TRANSLUCENT_PLOTS)
        for text, var in (("auto y scale", self.autoscale_var),
                          ("faint raw trace", self.show_raw_var),
                          ("see-through plots", self.translucent_var),
                          ("freeze display", self.paused_var)):
            Toggle(box, text, var).pack(anchor="w", fill="x")
        self.show_raw_var.trace_add("write", lambda *_: self._rebuild_figure())
        self.translucent_var.trace_add("write", lambda *_: self._rebuild_figure())

        # ---- backdrop ------------------------------------------------------
        box = self._card(p, "backdrop")
        row = tk.Frame(box, bg=PALETTE["surface"])
        row.pack(fill="x")
        self.backdrop_var = tk.StringVar(value=cfg.BACKDROP)
        ttk.Combobox(row, textvariable=self.backdrop_var, state="readonly",
                     font=FONTS["ui"], width=13,
                     values=["random"] + list(artwork.PIECES)).pack(side="left")
        self.opacity_var = tk.StringVar(value=cfg.BACKDROP_OPACITY)
        ttk.Combobox(row, textvariable=self.opacity_var, state="readonly",
                     font=FONTS["ui"], width=6,
                     values=list(cfg.BACKDROP_OPACITIES)).pack(side="right")
        RoundedButton(box, "shuffle", self._shuffle_backdrop).pack(fill="x", pady=(6, 0))
        self.backdrop_var.trace_add("write", lambda *_: self._rebuild_figure())
        self.opacity_var.trace_add("write", lambda *_: self._rebuild_figure())

        # ---- markers ------------------------------------------------------
        box = self._card(p, "markers")
        row = tk.Frame(box, bg=PALETTE["surface"])
        row.pack(fill="x")
        RoundedButton(row, "mark a", lambda: self._set_marker("a")).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        RoundedButton(row, "mark b", lambda: self._set_marker("b")).pack(
            side="left", fill="x", expand=True)
        self.marker_label = ttk.Label(box, text="a --   b --", style="Muted.TLabel")
        self.marker_label.pack(anchor="w", pady=(6, 0))
        ttk.Label(box, text="left-click plot sets a, right-click sets b",
                  style="Faint.TLabel").pack(anchor="w")

        row = tk.Frame(box, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(8, 0))
        self.event_var = tk.StringVar(value="event")
        entry = ttk.Entry(row, textvariable=self.event_var, font=FONTS["ui"])
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        entry.bind("<Return>", lambda e: self._add_event())
        RoundedButton(row, "log", self._add_event).pack(side="right")
        RoundedButton(box, "clear markers & events", self._clear_annotations).pack(
            fill="x", pady=(6, 0))

        # ---- save ---------------------------------------------------------
        box = self._card(p, "save")
        self.record_btn = RoundedButton(box, "\u25cf record", self._toggle_record,
                                        kind="danger")
        self.record_btn.pack(fill="x")
        RoundedButton(box, "save span a \u2192 b", lambda: self._save_span(True)).pack(
            fill="x", pady=(6, 0))
        RoundedButton(box, "save scroll-back", lambda: self._save_span(False)).pack(
            fill="x", pady=(4, 0))
        RoundedButton(box, "clear buffer", self._clear_buffer).pack(fill="x", pady=(4, 0))
        ttk.Label(box, text=f"scroll-back holds {cfg.HISTORY_SECONDS:g}s\n"
                            "recording streams to disk, no limit",
                  style="Faint.TLabel", justify="left").pack(anchor="w", pady=(8, 0))

        ttk.Label(p, text="\u03b3\u03bd\u1ff6\u03b8\u03b9 \u03c3\u03b5\u03b1\u03c5\u03c4\u03cc\u03bd",
                  style="Page.TLabel", foreground=PALETTE["faint"],
                  font=FONTS["tiny"], anchor="center").pack(fill="x", pady=14)

    def _populate_channels(self) -> None:
        """(Re)build the channel rows. Called again if the layout changes."""
        box = self._channels_box
        for child in box.winfo_children():
            child.destroy()
        ttk.Label(box, text="analog", style="Head.TLabel").pack(anchor="w")
        for ui in self.analog_ui:
            self._channel_row(box, ui, with_filter=True)
        tk.Frame(box, bg=PALETTE["line"], height=1).pack(fill="x", pady=8)
        ttk.Label(box, text="digital", style="Head.TLabel").pack(anchor="w")
        for ui in self.digital_ui:
            self._channel_row(box, ui, with_filter=False)
        ttk.Label(box, text="overlay puts a channel on the shared plot;\n"
                            "buttons there are drawn as shaded bands",
                  style="Faint.TLabel", justify="left").pack(anchor="w", pady=(8, 0))
        RoundedButton(box, "edit channels\u2026", self._edit_channels).pack(
            fill="x", pady=(8, 0))

    def _channel_row(self, parent, ui: ChannelUI, with_filter: bool) -> None:
        row = tk.Frame(parent, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(4, 0))

        top = tk.Frame(row, bg=PALETTE["surface"])
        top.pack(fill="x")
        swatch = tk.Canvas(top, width=9, height=9, highlightthickness=0, bd=0,
                           bg=PALETTE["surface"])
        swatch.create_rectangle(0, 3, 9, 6, fill=ui.color, outline=ui.color)
        swatch.pack(side="left", padx=(0, 6))
        Toggle(top, ui.name.lower(), ui.visible).pack(side="left")
        ui.visible.trace_add("write", lambda *_: self._rebuild_figure())

        opts = tk.Frame(row, bg=PALETTE["surface"])
        opts.pack(fill="x", padx=(15, 0), pady=(2, 0))
        ttk.Combobox(opts, textvariable=ui.view, width=11, state="readonly",
                     font=FONTS["small"],
                     values=["own", "overlay"]).pack(side="left")
        ui.view.trace_add("write", lambda *_: self._rebuild_figure())
        if with_filter:
            ttk.Combobox(opts, textvariable=ui.filter_name, width=11, state="readonly",
                         font=FONTS["small"], values=flt.PRESETS).pack(
                side="right", padx=(4, 0))
            ui.filter_name.trace_add("write", lambda *_a, u=ui: self._rebuild_chain(u))

    # ------------------------------------------------------- filter wiring --

    def _build_channel_ui(self) -> None:
        """Create the per-channel state from the current channel lists."""
        self.analog_ui = [
            ChannelUI(ch.name, i, False, ch.default_view,
                      ch.color or trace_color(i), ch.default_filter)
            for i, ch in enumerate(cfg.ANALOG_CHANNELS)
        ]
        self.digital_ui = [
            ChannelUI(ch.name, j, True, ch.default_view,
                      ch.color or trace_color(cfg.N_ANALOG + j))
            for j, ch in enumerate(cfg.DIGITAL_CHANNELS)
        ]

    def _adopt_layout(self, analog_names, digital_names) -> None:
        """Reshape the whole app around a different set of channels."""
        cfg.apply_layout(analog_names, digital_names)
        settings.apply_saved()           # a layout set up in the app beats the defaults
        self._build_channel_ui()
        self._rebuild_chains()
        self._populate_channels()
        self._rebuild_figure()

    def _edit_channels(self) -> None:
        """Add, rename, reorder or remove channels without touching config.py."""
        if self.review is not None:
            messagebox.showinfo("alcmaeon",
                                "press 'back to live input' before changing channels")
            return

        win = tk.Toplevel(self)
        win.title("channels")
        win.configure(bg=PALETTE["bg"])
        win.geometry("620x680")
        win.transient(self)

        tk.Label(win, text="channels", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=FONTS["title"]).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(win, text="one entry per pin, in the same order as ANALOG_PINS "
                           "and DIGITAL_PINS in the arduino sketch",
                 bg=PALETTE["bg"], fg=PALETTE["muted"], font=FONTS["small"],
                 wraplength=560, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        body = tk.Frame(win, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True, padx=20)

        analog_rows: list[dict] = []
        digital_rows: list[dict] = []

        def add_analog(name="", zero=False, filt="Raw", view="own"):
            analog_rows.append({"name": tk.StringVar(value=name),
                                "zero": tk.BooleanVar(value=zero),
                                "filter": filt, "view": view})

        def add_digital(name="", view="overlay"):
            digital_rows.append({"name": tk.StringVar(value=name), "view": view})

        for channel in cfg.ANALOG_CHANNELS:
            add_analog(channel.name, channel.zero_center,
                       channel.default_filter, channel.default_view)
        for channel in cfg.DIGITAL_CHANNELS:
            add_digital(channel.name, channel.default_view)

        def redraw():
            for child in body.winfo_children():
                child.destroy()

            def section(title, note):
                tk.Label(body, text=title, bg=PALETTE["bg"], fg=PALETTE["blue"],
                         font=FONTS["label"]).pack(anchor="w", pady=(6, 0))
                tk.Label(body, text=note, bg=PALETTE["bg"], fg=PALETTE["faint"],
                         font=FONTS["tiny"]).pack(anchor="w", pady=(0, 4))

            section("analog inputs", "tick 'biopotential' for EMG or ECG "
                                     "(centres the signal and enables contraction detection)")
            for index, row in enumerate(analog_rows):
                line = tk.Frame(body, bg=PALETTE["bg"])
                line.pack(fill="x", pady=2)
                tk.Label(line, text=f"{index + 1}.", bg=PALETTE["bg"],
                         fg=PALETTE["faint"], font=FONTS["small"], width=3).pack(side="left")
                ttk.Entry(line, textvariable=row["name"], font=FONTS["ui"]).pack(
                    side="left", fill="x", expand=True)
                Toggle(line, "biopotential", row["zero"], bg=PALETTE["bg"],
                       font_key="small").pack(side="left", padx=8)
                RoundedButton(line, "\u2715", lambda i=index: remove(analog_rows, i),
                              page_bg=PALETTE["bg"], height=24).pack(side="left")
            RoundedButton(body, "+ add analog input",
                          lambda: (add_analog(f"Analog {len(analog_rows) + 1}"), redraw()),
                          page_bg=PALETTE["bg"]).pack(fill="x", pady=(6, 12))

            section("digital inputs", "buttons, switches, triggers")
            for index, row in enumerate(digital_rows):
                line = tk.Frame(body, bg=PALETTE["bg"])
                line.pack(fill="x", pady=2)
                tk.Label(line, text=f"{index + 1}.", bg=PALETTE["bg"],
                         fg=PALETTE["faint"], font=FONTS["small"], width=3).pack(side="left")
                ttk.Entry(line, textvariable=row["name"], font=FONTS["ui"]).pack(
                    side="left", fill="x", expand=True)
                RoundedButton(line, "\u2715", lambda i=index: remove(digital_rows, i),
                              page_bg=PALETTE["bg"], height=24).pack(side="left", padx=(8, 0))
            RoundedButton(body, "+ add digital input",
                          lambda: (add_digital(f"Digital {len(digital_rows) + 1}"), redraw()),
                          page_bg=PALETTE["bg"]).pack(fill="x", pady=(6, 0))

            info = getattr(self.source, "device_info", None)
            if info:
                tk.Label(body, text=f"connected board reports {info['analog']} analog "
                                    f"and {info['digital']} digital",
                         bg=PALETTE["bg"], fg=PALETTE["muted"],
                         font=FONTS["small"]).pack(anchor="w", pady=(14, 2))
                RoundedButton(body, "match the connected board", match_board,
                              page_bg=PALETTE["bg"]).pack(fill="x")

        def remove(rows, index):
            if len(rows) <= 1 and rows is analog_rows:
                messagebox.showinfo("alcmaeon", "at least one analog input is needed")
                return
            rows.pop(index)
            redraw()

        def match_board():
            info = getattr(self.source, "device_info", None)
            if not info:
                return
            while len(analog_rows) > info["analog"]:
                analog_rows.pop()
            while len(analog_rows) < info["analog"]:
                add_analog(f"Analog {len(analog_rows) + 1}")
            while len(digital_rows) > info["digital"]:
                digital_rows.pop()
            while len(digital_rows) < info["digital"]:
                add_digital(f"Digital {len(digital_rows) + 1}")
            redraw()

        def save_and_close():
            analog = [{"name": row["name"].get().strip() or f"Analog {i + 1}",
                       "zero_center": bool(row["zero"].get()),
                       "filter": row["filter"], "view": row["view"]}
                      for i, row in enumerate(analog_rows)]
            digital = [{"name": row["name"].get().strip() or f"Digital {j + 1}",
                        "view": row["view"]}
                       for j, row in enumerate(digital_rows)]
            win.destroy()
            self._apply_channel_edit(analog, digital)

        footer = tk.Frame(win, bg=PALETTE["bg"])
        footer.pack(fill="x", padx=20, pady=16)
        RoundedButton(footer, "cancel", win.destroy, page_bg=PALETTE["bg"]).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        RoundedButton(footer, "save channels", save_and_close, kind="primary",
                      page_bg=PALETTE["bg"]).pack(side="left", fill="x", expand=True)

        redraw()

    def _apply_channel_edit(self, analog, digital) -> None:
        """Put an edited channel list into effect and remember it."""
        was_live = self.source is not None
        if was_live:
            self._disconnect()

        cfg.apply_layout_spec(analog, digital)
        self._saved_layout = None
        self._build_channel_ui()
        self._rebuild_chains()
        self._populate_channels()
        self._resize_buffer()
        self._rebuild_figure()

        stored = settings.save(settings.describe_current())
        note = "" if stored else "  ·  could not be saved to disk"
        self._set_status(f"channels set to {cfg.N_ANALOG} analog and "
                         f"{cfg.N_DIGITAL} digital{note}")
        if was_live:
            self._set_status(f"channels updated \u00b7 {cfg.N_ANALOG} analog, "
                             f"{cfg.N_DIGITAL} digital \u00b7 press connect again")

    def _rebuild_chains(self) -> None:
        for ui in self.analog_ui:
            ui.chain = flt.build_chain(ui.filter_name.get(), self.settings)

    def _rebuild_chain(self, ui: ChannelUI) -> None:
        ui.chain = flt.build_chain(ui.filter_name.get(), self.settings)
        self._rebuild_figure()          # legend shows the filter name
        self._set_status(f"{ui.name} \u00b7 {ui.filter_name.get()} \u00b7 "
                         f"{flt.PRESET_HELP.get(ui.filter_name.get(), '')}")

    def _apply_filter_settings(self) -> None:
        try:
            self.settings.fs = float(self.rate_var.get())
            self.settings.highpass_hz = float(self.hp_var.get())
            self.settings.lowpass_hz = float(self.lp_var.get())
            self.settings.notch_hz = float(self.notch_var.get())
            self.settings.notch_q = float(self.q_var.get())
            self.settings.envelope_hz = float(self.env_var.get())
            self.settings.rms_ms = float(self.rms_var.get())
            self.settings.smooth_ms = float(self.smooth_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("alcmaeon", "filter values must be numbers")
            return
        nyquist = 0.5 * self.settings.fs
        if self.settings.lowpass_hz >= nyquist:
            self._set_status(f"low-pass clamped below nyquist ({nyquist:g} hz)")
        self._rebuild_chains()
        self._set_status("filters applied \u00b7 affects samples from now on")

    # ---------------------------------------------------------- connection --

    def _refresh_ports(self) -> None:
        ports = available_ports()
        self.port_combo.configure(values=ports)
        if self.port_var.get() not in ports:
            self.port_var.set(ports[0])
        self._set_status(f"{len(ports) - 1} serial port(s) found")

    def _toggle_connection(self) -> None:
        if self.source is not None:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        try:
            self.sample_rate = float(self.rate_var.get())
            baud = int(self.baud_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("alcmaeon", "baud and sample rate must be numbers")
            return

        if self.review is not None:
            self._back_to_live()

        self.settings.fs = self.sample_rate
        self._rebuild_chains()
        self._resize_buffer()
        while not self.sample_queue.empty():
            self.sample_queue.get_nowait()

        port = self.port_var.get()
        self.source = make_source(port, baud, self.sample_rate, self.sample_queue)
        self._checked_device = False
        self.source.start()
        self.connect_btn.set_text("disconnect")
        self._rate_marker = (time.time(), 0)
        self._total_samples = 0
        self._set_status(f"connected \u00b7 {port}")

    def _disconnect(self) -> None:
        if self.source is not None:
            self.source.stop()
            self.source.join(timeout=2.0)
            self.source = None
        self.connect_btn.set_text("connect")
        if self.recorder.active:
            self._toggle_record()
        self._set_status("disconnected")

    def _resize_buffer(self) -> None:
        capacity = max(1000, int(cfg.HISTORY_SECONDS * self.sample_rate))
        self.buffer = RingBuffer(capacity, 2 * cfg.N_ANALOG + cfg.N_DIGITAL)
        self.live_buffer = self.buffer

    # ------------------------------------------------------------- polling --

    def _poll(self) -> None:
        drained = 0
        try:
            while drained < 5000:
                self._ingest(self.sample_queue.get_nowait())
                drained += 1
        except queue.Empty:
            pass

        if cfg.CHECK_DEVICE_CHANNELS and not self._checked_device:
            self._check_device_channels()

        if self.source is not None and self.source.error:
            error = self.source.error
            self._disconnect()
            messagebox.showerror("alcmaeon", error)
            self._set_status(error)

        now = time.time()
        if drained:
            self._total_samples += drained
            elapsed = now - self._rate_marker[0]
            if elapsed >= 1.0:
                self._measured_rate = (self._total_samples - self._rate_marker[1]) / elapsed
                self._rate_marker = (now, self._total_samples)

        if not self.paused_var.get() and now - self._last_draw >= 1.0 / cfg.PLOT_FPS:
            self._redraw()
            self._last_draw = now
            self._update_status_line()

        self.after(cfg.POLL_MS, self._poll)

    def _check_device_channels(self) -> None:
        """Compare what the board says it sends against how the app is set up.

        Without this a mismatched sketch just produces silence: every line has
        the wrong number of fields, so all of them are discarded and the graphs
        stay empty with no explanation.
        """
        info = getattr(self.source, "device_info", None)
        if info is None:
            # No reply yet. If lines are pouring in and all of them are being
            # rejected, say so anyway.
            source = self.source
            if source is not None and getattr(source, "bad_lines", 0) > 200 \
                    and source.samples_read == 0:
                self._checked_device = True
                self._disconnect()
                messagebox.showwarning(
                    "alcmaeon",
                    "Data is arriving but none of it can be read.\n\n"
                    "The usual cause is a channel count that does not match: "
                    f"this app expects {cfg.N_ANALOG} analog and "
                    f"{cfg.N_DIGITAL} digital channels.\n\n"
                    "Check ANALOG_PINS / DIGITAL_PINS in the Arduino sketch "
                    "against ANALOG_CHANNELS / DIGITAL_CHANNELS in config.py, "
                    "and that the baud rate matches.")
            return

        self._checked_device = True
        analog, digital = info.get("analog"), info.get("digital")
        if analog == cfg.N_ANALOG and digital == cfg.N_DIGITAL:
            rate = info.get("sample_rate")
            if rate and abs(rate - self.sample_rate) > 1:
                self._set_status(f"note: board reports {rate:.0f} hz, "
                                 f"app is set to {self.sample_rate:.0f} hz")
            return

        self._disconnect()
        if messagebox.askyesno(
                "alcmaeon",
                "The board and the app disagree about the channels.\n\n"
                f"Arduino is sending:   {analog} analog, {digital} digital\n"
                f"This app expects:     {cfg.N_ANALOG} analog, {cfg.N_DIGITAL} digital\n\n"
                "Nothing can be plotted until they match.\n\n"
                "Set the app up to match the board now?"):
            self._match_board(analog, digital)

    def _match_board(self, analog: int, digital: int) -> None:
        """Reshape the channel list to the counts the board reported.

        Existing channels keep their names and settings; anything extra is
        added with a placeholder name, renameable in the channel editor.
        """
        current = settings.describe_current()
        analog_spec = current["analog"][:analog]
        while len(analog_spec) < analog:
            analog_spec.append({"name": f"Analog {len(analog_spec) + 1}",
                                "zero_center": False, "filter": "Raw", "view": "own"})
        digital_spec = current["digital"][:digital]
        while len(digital_spec) < digital:
            digital_spec.append({"name": f"Digital {len(digital_spec) + 1}",
                                 "view": "overlay"})
        self._apply_channel_edit(analog_spec, digital_spec)
        self._set_status(f"channels matched to the board \u00b7 {analog} analog, "
                         f"{digital} digital \u00b7 press connect")

    def _ingest(self, sample: Sample) -> None:
        """One sample: scale -> filter -> ring buffer -> CSV."""
        values = np.empty(2 * cfg.N_ANALOG + cfg.N_DIGITAL, dtype=np.float32)
        for i, ch in enumerate(cfg.ANALOG_CHANNELS):
            raw = cfg.counts_to_volts(sample.analog[i], ch)
            values[i] = raw
            values[cfg.N_ANALOG + i] = self.analog_ui[i].chain.process(raw)
        for j in range(cfg.N_DIGITAL):
            values[2 * cfg.N_ANALOG + j] = sample.digital[j]

        self.buffer.append(sample.device_s, sample.wall_s, values)
        if self.recorder.active:
            self.recorder.write(sample.device_s, sample.wall_s, values)

    # -------------------------------------------------- opening saved files --

    def _open_recording(self) -> None:
        path = filedialog.askopenfilename(
            title="open a recording",
            filetypes=[("Alcmaeon CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            recording = loader.load_recording(path)
        except loader.LoadError as exc:
            messagebox.showerror("alcmaeon", str(exc))
            return
        except Exception as exc:                              # noqa: BLE001
            messagebox.showerror("alcmaeon", f"could not read that file:\n{exc}")
            return

        if self.source is not None:
            self._disconnect()
        if self.review is None:
            self.live_buffer = self.buffer          # keep the live data to return to

        # The file names its own channels. If they differ from the current
        # setup, follow the file rather than refusing to open it.
        if not recording.matches():
            summary = (f"This recording has {len(recording.analog_names)} analog "
                       f"and {len(recording.digital_names)} digital channels:\n\n"
                       f"   {', '.join(recording.analog_names)}\n"
                       f"   {', '.join(recording.digital_names) or '(none)'}\n\n"
                       f"Your setup has {cfg.N_ANALOG} analog and "
                       f"{cfg.N_DIGITAL} digital.\n\n"
                       "Display it using the channels in the file?")
            if not messagebox.askyesno("alcmaeon", summary):
                return
            if self._saved_layout is None:
                self._saved_layout = cfg.current_layout()
            self._adopt_layout(recording.analog_names, recording.digital_names)

        columns = 2 * cfg.N_ANALOG + cfg.N_DIGITAL
        buffer = RingBuffer(max(16, recording.t.size), columns)
        buffer.fill(recording.t, recording.wall, recording.data)
        self.buffer = buffer
        self.review = recording

        self.events = list(recording.events)
        self.mark_a = self.mark_b = None
        self._update_marker_label()
        self.view_start = float(recording.t[0]) if recording.t.size else 0.0

        name = path.replace("\\", "/").split("/")[-1]
        self.file_label.configure(text=f"{name}\n{recording.summary()}")
        self.review_box.pack(fill="x")
        self._sync_scrub()
        self._rebuild_figure()
        self._set_status(f"opened {name} \u00b7 {recording.summary()}")

    def _back_to_live(self) -> None:
        restored = False
        if self._saved_layout is not None:
            cfg.restore_layout(self._saved_layout)
            self._saved_layout = None
            self._build_channel_ui()
            self._rebuild_chains()
            self._populate_channels()
            restored = True

        self.review = None
        if self.live_buffer.n_columns != 2 * cfg.N_ANALOG + cfg.N_DIGITAL:
            self._resize_buffer()               # layout changed under it
        else:
            self.buffer = self.live_buffer
        self.events = []
        self.mark_a = self.mark_b = None
        self._update_marker_label()
        self.review_box.pack_forget()
        self.file_label.configure(text="live input")
        self._rebuild_figure()
        self._set_status("back to live input" +
                         ("  ·  your own channels restored" if restored else ""))

    def _window_seconds(self) -> float:
        """Width of the visible window, honouring 'fit whole recording'."""
        if self.review is not None and self.fit_var.get():
            return max(self.review.duration, 0.001)
        return float(self.window_var.get())

    def _sync_scrub(self) -> None:
        """Match the timeline slider to the recording length and zoom."""
        if self.review is None:
            return
        span = max(0.0, self.review.duration - self._window_seconds())
        self.scrub.configure(to=max(span, 0.001))
        if self.scrub_var.get() > span:
            self.scrub_var.set(span)
        self._on_scrub(None)

    def _on_scrub(self, _value) -> None:
        if self.review is None:
            return
        offset = float(self.scrub_var.get())
        self.view_start = float(self.review.t[0]) + offset
        window = self._window_seconds()
        # shown relative to the start of the file, which is what you scrub by
        self.scrub_label.configure(
            text=f"{offset:.2f}s \u2192 {min(offset + window, self.review.duration):.2f}s"
                 f"   of {self.review.duration:.2f}s")

    # -------------------------------------------------------------- analysis --

    def _analyse(self) -> None:
        if len(self.buffer) < 10:
            messagebox.showinfo("alcmaeon", "there is not enough data to analyse yet")
            return

        if self.mark_a is not None and self.mark_b is not None:
            t, _wall, data = self.buffer.between(self.mark_a, self.mark_b)
            label = f"markers a \u2192 b"
        else:
            t, _wall, data = self.buffer.snapshot()
            label = ("whole recording" if self.review is not None
                     else "live scroll-back")
        if self.review is not None:
            label += f" \u00b7 {self.review.path.replace(chr(92), '/').split('/')[-1]}"

        if t.size < 10:
            messagebox.showinfo("alcmaeon", "that span is too short to analyse")
            return

        report = analysis.analyse(t, data, label=label)
        self._show_report(analysis.format_report(report))
        self._set_status(f"analysed {t.size} samples \u00b7 {label}")

    def _show_report(self, text: str) -> None:
        window = tk.Toplevel(self)
        window.title("alcmaeon \u00b7 analysis")
        window.configure(bg=PALETTE["bg"])
        window.geometry("760x680")

        header = tk.Frame(window, bg=PALETTE["bg"])
        header.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(header, text="analysis", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=FONTS["title"]).pack(side="left")

        frame = tk.Frame(window, bg=PALETTE["bg"])
        frame.pack(fill="both", expand=True, padx=18)
        box = tk.Text(frame, bg=PALETTE["surface"], fg=PALETTE["text"], bd=0,
                      font=FONTS["ui"], wrap="none", highlightthickness=0,
                      padx=14, pady=12, insertbackground=PALETTE["blue"])
        bar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=bar.set)
        box.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        box.insert("1.0", text)
        box.configure(state="disabled")

        buttons = tk.Frame(window, bg=PALETTE["bg"])
        buttons.pack(fill="x", padx=18, pady=14)
        RoundedButton(buttons, "save report\u2026",
                      lambda: self._save_report(text), page_bg=PALETTE["bg"]).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        RoundedButton(buttons, "close", window.destroy,
                      page_bg=PALETTE["bg"]).pack(side="left", fill="x", expand=True)

    def _save_report(self, text: str) -> None:
        path = filedialog.asksaveasfilename(
            title="save report", defaultextension=".txt",
            initialfile=rec.suggest_filename("alcmaeon_analysis").replace(
                "\\", "/").split("/")[-1].replace(".csv", ".txt"),
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self._set_status(f"report saved \u00b7 {path}")

    # ------------------------------------------------------------ backdrop --

    def _shuffle_backdrop(self) -> None:
        self.backdrop_var.set("random")
        self._rebuild_figure()
        self._set_status(f"backdrop \u00b7 {self._backdrop_name}")

    def _draw_backdrop(self) -> None:
        """White line art behind everything, on its own full-figure axes."""
        alpha = cfg.BACKDROP_OPACITIES.get(self.opacity_var.get(), 0.10)
        if alpha <= 0:
            self._backdrop_name = "off"
            return

        ax = self.figure.add_axes([0, 0, 1, 1], zorder=-10)
        ax.set_in_layout(False)
        ax.patch.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        name, polylines = artwork.get(self.backdrop_var.get())
        self._backdrop_name = name
        for poly in polylines:
            ax.plot(poly[:, 0], poly[:, 1], color=PALETTE["art"], linewidth=1.0,
                    alpha=alpha, solid_joinstyle="round", solid_capstyle="round",
                    zorder=-10)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.22, 1.22)          # margin: art fills ~70% of the height
        ax.set_aspect("equal", adjustable="datalim")   # keeps art undistorted on resize
        self._bg_ax = ax

    # ------------------------------------------------------------ plotting --

    def _visible_groups(self):
        overlay = [ui for ui in self.analog_ui + self.digital_ui
                   if ui.mode == "overlay"]
        own = [ui for ui in self.analog_ui + self.digital_ui if ui.mode == "own"]
        groups = []
        if overlay:
            groups.append(("main", overlay))
        groups.extend((ui.key, [ui]) for ui in own)
        return groups

    def _rebuild_figure(self) -> None:
        """Recreate axes and lines. Called when layout or visibility changes."""
        self.figure.clear()
        self._bg_ax = None
        self.axes: dict[str, object] = {}
        self.lines: dict[str, object] = {}
        self.shading: list = []
        self.marker_artists: list = []
        self.overlay_artists: list = []      # redrawn every frame, never cached
        self._clock = None
        self._draw_backdrop()

        translucent = self.translucent_var.get()
        groups = self._visible_groups()
        if not groups:
            ax = self.figure.add_subplot(1, 1, 1)
            style_axes(ax, translucent)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "no channels selected", ha="center", va="center",
                    color=PALETTE["faint"], fontsize=9, transform=ax.transAxes)
            self.canvas.draw_idle()
            return

        # a 0/1 button trace needs far less height than a signal
        ratios = [0.45 if all(m.is_digital for m in members) else 1.0
                  for _key, members in groups]
        gridspec = self.figure.add_gridspec(len(groups), 1, height_ratios=ratios)

        for row, (key, members) in enumerate(groups):
            ax = self.figure.add_subplot(gridspec[row, 0])
            style_axes(ax, translucent)
            self.axes[key] = ax

            for ui in members:
                if ui.is_digital and key == "main":
                    continue                       # shaded band instead of a line
                if ui.is_digital:
                    line, = ax.step([], [], where="post", color=ui.color,
                                    linewidth=1.4, animated=cfg.FAST_PLOT,
                                    label=ui.name.lower())
                    ax.set_ylim(-0.15, 1.15)
                    ax.set_yticks([0, 1])
                    ax.set_yticklabels(["off", "on"])
                    self.lines[ui.key] = line
                else:
                    if self.show_raw_var.get():
                        faint, = ax.plot([], [], color=ui.color, linewidth=0.6,
                                         alpha=0.25, animated=cfg.FAST_PLOT)
                        self.lines[ui.key + ":raw"] = faint
                    line, = ax.plot([], [], color=ui.color, linewidth=1.1,
                                    animated=cfg.FAST_PLOT,
                                    label=f"{ui.name.lower()}  {ui.filter_name.get().lower()}")
                    self.lines[ui.key] = line

            named = [m for m in members if not (m.is_digital and key == "main")]
            names = " \u00b7 ".join(m.name.lower() for m in named or members)
            ax.set_ylabel(names if len(names) < 30 else names[:28] + "\u2026")

            handles, labels = ax.get_legend_handles_labels()
            for ui in members:
                if ui.is_digital and key == "main":
                    handles.append(Patch(facecolor=ui.color, alpha=0.4))
                    labels.append(f"{ui.name.lower()}  pressed")
            if handles:
                ax.legend(handles, labels, **legend_kwargs())
            if row == 0:
                # top right, above the first plot: reads as a clock for the
                # whole view rather than a label belonging to one channel
                self._clock = ax.text(
                    1.0, 1.015, "", transform=ax.transAxes, ha="right", va="bottom",
                    color=PALETTE["muted"], fontsize=7.5, family="monospace",
                    clip_on=False, animated=cfg.FAST_PLOT)
                self.overlay_artists.append(self._clock)
            if row == len(groups) - 1:
                ax.set_xlabel("seconds ago" if cfg.FAST_PLOT else "seconds")
            else:
                ax.tick_params(labelbottom=False)

        self._limits = {}
        self._envelope = {}
        self._apply_xlimits()
        self._invalidate_background(relayout=True)
        self.canvas.draw_idle()

    def _apply_xlimits(self) -> None:
        """Fast mode keeps the x-axis fixed at [-window, 0] and slides the data
        through it. Static limits are what make the cached background valid."""
        if not cfg.FAST_PLOT:
            return
        window = self._window_seconds()
        for ax in getattr(self, "axes", {}).values():
            ax.set_xlim(-window, 0.0)

    def _redraw(self) -> None:
        if not getattr(self, "axes", None):
            return
        window = self._window_seconds()
        if self.review is not None:
            t_start = self.view_start
            t_end = t_start + window
            t, wall, data = self.buffer.between(t_start, t_end)
        else:
            t, wall, data = self.buffer.last_seconds(window)
            if t.size == 0:
                return
            t_end = t[-1]
            t_start = max(t_end - window, self.buffer.oldest_time)
        if t.size == 0:
            return

        fast = cfg.FAST_PLOT
        # In fast mode the axis is fixed and the data slides through it.
        shift = t_end if fast else 0.0
        self._update_clock(t, wall, t_end)

        def reduce(values):
            """Thin a trace for drawing, then move it onto the display axis.

            Decimation runs on absolute time on purpose: its bucket edges are
            anchored to it, which is what stops peaks flickering as the window
            slides. Shifting first would move the buckets every frame.
            """
            times, points = decimate(t, values, cfg.MAX_PLOT_POINTS)
            return times - shift, points

        for artist in self.shading + self.marker_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self.shading.clear()
        self.marker_artists.clear()

        rescaled = False
        for key, ax in self.axes.items():
            members = [ui for ui in self.analog_ui + self.digital_ui
                       if (ui.mode == "overlay" and key == "main")
                       or (ui.mode == "own" and ui.key == key)]
            lo, hi = np.inf, -np.inf

            for ui in members:
                if ui.is_digital:
                    y = data[:, 2 * cfg.N_ANALOG + ui.index]
                    if key == "main":
                        self._shade_digital(ax, t - shift, y, ui)
                        continue
                    xd, yd = reduce(y)
                    self.lines[ui.key].set_data(xd, yd)
                    continue

                xd, yd = reduce(data[:, cfg.N_ANALOG + ui.index])
                self.lines[ui.key].set_data(xd, yd)
                lo, hi = min(lo, float(np.min(yd))), max(hi, float(np.max(yd)))

                raw_line = self.lines.get(ui.key + ":raw")
                if raw_line is not None:
                    xr, yr = reduce(data[:, ui.index])
                    raw_line.set_data(xr, yr)
                    lo, hi = min(lo, float(np.min(yr))), max(hi, float(np.max(yr)))

            if not fast:
                ax.set_xlim(t_start, t_end if t_end > t_start else t_start + window)
            if self.autoscale_var.get() and key not in self._manual_axes \
                    and np.isfinite(lo) and np.isfinite(hi):
                if self._rescale(ax, key, lo, hi, fast):
                    rescaled = True
            if members and all(m.is_digital for m in members) and key != "main":
                ax.set_ylim(-0.15, 1.15)

            self._draw_markers(ax, t_start, t_end, t_end if fast else 0.0)

        if not fast:
            self.canvas.draw_idle()
            return

        # Any limit change means the cached bitmap no longer matches the axes.
        if rescaled:
            self._invalidate_background()
        self._blit()

    @staticmethod
    def _nice_limits(lo: float, hi: float, headroom: float) -> tuple[float, float]:
        """Round a range out to tidy step boundaries.

        Quantising is what stops the hitching: two bursts of slightly different
        size land on the *same* limits, so the axes never change and the cached
        background stays valid.
        """
        span = max(hi - lo, 1e-9)
        lo -= span * headroom
        hi += span * headroom
        span = hi - lo
        base = 10.0 ** math.floor(math.log10(span))
        step = base
        for mult in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0):
            step = base * mult
            if span / step <= 5:
                break
        return (math.floor(lo / step) * step, math.ceil(hi / step) * step)

    def _rescale(self, ax, key: str, lo: float, hi: float, fast: bool) -> bool:
        """Set the y range. Returns True if the axes actually changed.

        In fast mode a change costs a full redraw, which is visible as a hitch,
        so the range tracks a slow envelope of the signal rather than the
        current window, and is quantised so equivalent ranges compare equal.
        """
        if not fast:
            span = max(hi - lo, 1e-4)
            ax.set_ylim(lo - 0.12 * span, hi + 0.12 * span)
            return False

        now = time.time()
        previous = self._envelope.get(key)
        if previous is None:
            # Seed wide. A signal almost always grows past its first half
            # second, and every one of those growths would cost a redraw.
            middle = (lo + hi) / 2.0
            reach = max(hi - lo, 1e-6) * cfg.AUTOSCALE_INITIAL_REACH
            env_lo, env_hi, stamp = middle - reach, middle + reach, now
        else:
            env_lo, env_hi, stamp = previous
            env_lo = min(env_lo, lo)          # grow immediately
            env_hi = max(env_hi, hi)
            # Ease back down on a long half-life. Anything faster collapses the
            # range during the quiet gap between bursts, so the next burst
            # clips and forces a redraw -- which is exactly the periodic hitch.
            dt = max(0.0, now - stamp)
            pull = 1.0 - 0.5 ** (dt / max(cfg.AUTOSCALE_HALF_LIFE, 0.1))
            env_lo += (lo - env_lo) * pull
            env_hi += (hi - env_hi) * pull
            stamp = now
        self._envelope[key] = (env_lo, env_hi, stamp)

        target = self._nice_limits(env_lo, env_hi, cfg.AUTOSCALE_HEADROOM)
        current = self._limits.get(key)
        if current is not None and abs(current[0] - target[0]) < 1e-9 \
                and abs(current[1] - target[1]) < 1e-9:
            return False                      # same tidy range -> nothing to redraw

        if current is not None:
            # Only two things justify the cost of a redraw: the signal has left
            # the visible range, or it has become so small the view is useless.
            # Merely drifting toward a different tidy range is not worth a hitch.
            clipped = lo < current[0] or hi > current[1]
            dwarfed = (hi - lo) < (current[1] - current[0]) * cfg.AUTOSCALE_SHRINK_AT
            if not clipped and not (dwarfed and
                                    now - self._last_rescale >= cfg.AUTOSCALE_MIN_INTERVAL):
                return False

        self._last_rescale = now
        ax.set_ylim(*target)
        self._limits[key] = target
        return True

    def _update_clock(self, t, wall, t_end: float) -> None:
        """Show the real time at the right-hand edge of the view.

        The x-axis reads "seconds ago" and never moves, which is what makes the
        cached background reusable -- but it also means nothing on screen shows
        time passing. This does.
        """
        if self._clock is None or t.size == 0:
            return
        stamp = float(wall[-1]) if wall.size and wall[-1] > 0 else 0.0
        clock = rec.iso(stamp)[11:19] if stamp else "--:--:--"
        if self.review is not None:
            self._clock.set_text(f"{clock}   ·   {t_end:.2f}s into recording")
        else:
            self._clock.set_text(f"{clock}   ·   {t_end:.1f}s elapsed   ·   now \u25b8")

    def _blit(self) -> None:
        """Draw only the moving parts on top of the cached static layer."""
        canvas = self.canvas
        # Compare against the live canvas size rather than trusting resize
        # events: if the window changed after the bitmap was captured, a stale
        # one paints the figure at the old size and leaves a dead margin.
        size = (int(self.figure.bbox.width), int(self.figure.bbox.height))
        if self._background is None or self._background_size != size:
            if self._layout_pending:
                # Constrained layout is the single most expensive part of a
                # draw, and it only needs to run when the figure structure or
                # the window size changes -- not every time the y range moves.
                self.figure.set_layout_engine("constrained")
                canvas.draw()
                self.figure.set_layout_engine("none")
                self._layout_pending = False
            canvas.draw()                       # renders everything but animated artists
            self._background = canvas.copy_from_bbox(self.figure.bbox)
            self._background_size = size
        canvas.restore_region(self._background)

        for key, ax in self.axes.items():
            for line in ax.lines:
                if line.get_animated():
                    ax.draw_artist(line)
        for artist in self.shading + self.marker_artists + self.overlay_artists:
            try:
                artist.axes.draw_artist(artist)
            except Exception:
                pass

        canvas.blit(self.figure.bbox)

    def _shade_digital(self, ax, t, y, ui: ChannelUI) -> None:
        """A button press becomes a translucent band across the signal plot."""
        if not np.any(y > 0.5):
            return
        band = ax.fill_between(t, 0, 1, where=(y > 0.5),
                               transform=ax.get_xaxis_transform(),
                               color=ui.color, alpha=0.11, linewidth=0, step="post",
                               animated=cfg.FAST_PLOT)
        self.shading.append(band)

    def _draw_markers(self, ax, t_start: float, t_end: float,
                      offset: float = 0.0) -> None:
        """Markers live on absolute time; `offset` shifts them onto the
        sliding axis used in fast mode (where 0 is 'now')."""
        animated = cfg.FAST_PLOT

        def place(value):
            return value - offset

        for value, label, dash in ((self.mark_a, "a", (4, 3)), (self.mark_b, "b", (1, 2))):
            if value is not None and t_start <= value <= t_end:
                self.marker_artists.append(
                    ax.axvline(place(value), color=MARKER_COLOR, linewidth=1.1,
                               dashes=dash, animated=animated))
                self.marker_artists.append(
                    ax.text(place(value), 0.985, f" {label}",
                            transform=ax.get_xaxis_transform(), color=MARKER_COLOR,
                            fontsize=7, va="top", animated=animated))
        if self.mark_a is not None and self.mark_b is not None:
            lo, hi = sorted((self.mark_a, self.mark_b))
            if hi >= t_start and lo <= t_end:
                self.marker_artists.append(
                    ax.axvspan(max(lo, t_start) - offset, min(hi, t_end) - offset,
                               color=MARKER_COLOR, alpha=0.06, animated=animated))
        for t_event, label in self.events:
            if t_start <= t_event <= t_end:
                self.marker_artists.append(
                    ax.axvline(place(t_event), color=EVENT_COLOR, linewidth=0.9,
                               alpha=0.85, animated=animated))
                self.marker_artists.append(
                    ax.text(place(t_event), 0.02, f" {label}",
                            transform=ax.get_xaxis_transform(), color=EVENT_COLOR,
                            fontsize=6.5, rotation=90, va="bottom", animated=animated))

    # --------------------------------------------------- markers and events --

    def _on_plot_click(self, event) -> None:
        if getattr(event, "dblclick", False) and self._release_axes(event):
            return
        if event.xdata is None:
            return
        if cfg.FAST_PLOT:
            # the axis reads "seconds ago"; markers are stored as absolute time
            anchor = (self.view_start + self._window_seconds()
                      if self.review is not None else self.buffer.newest_time)
            event = type("E", (), {"xdata": float(event.xdata) + anchor,
                                   "button": event.button})()
        if event.button == 1:
            self.mark_a = float(event.xdata)
        elif event.button == 3:
            self.mark_b = float(event.xdata)
        self._update_marker_label()

    def _on_plot_scroll(self, event) -> None:
        """Wheel over a plot changes that plot's amplitude range.

        Scaling by hand pins the axes: auto-scaling stops touching it until you
        double-click to hand it back.
        """
        if event.inaxes is None:
            return
        key = next((k for k, ax in self.axes.items() if ax is event.inaxes), None)
        if key is None:
            return

        factor = 1 / 1.25 if event.button == "up" else 1.25     # up = zoom in
        low, high = event.inaxes.get_ylim()
        centre = event.ydata if event.ydata is not None else (low + high) / 2
        span = (high - low) * factor / 2
        if span < 1e-9 or span > 1e9:
            return
        limits = (centre - span, centre + span)

        event.inaxes.set_ylim(*limits)
        self._limits[key] = limits
        self._manual_axes.add(key)
        self._invalidate_background()
        self._set_status(f"{self._axes_label(key)} range {limits[0]:.3g} to "
                         f"{limits[1]:.3g}   ·   double-click to auto-fit again")

    def _axes_label(self, key: str) -> str:
        if key == "main":
            return "main plot"
        for ui in self.analog_ui + self.digital_ui:
            if ui.key == key:
                return ui.name.lower()
        return key

    def _release_axes(self, event) -> bool:
        """Double-click hands an axes back to auto-scaling."""
        key = next((k for k, ax in self.axes.items() if ax is event.inaxes), None)
        if key is None or key not in self._manual_axes:
            return False
        self._manual_axes.discard(key)
        self._limits.pop(key, None)
        self._envelope.pop(key, None)
        self._invalidate_background()
        self._set_status(f"{self._axes_label(key)} back to auto scale")
        return True

    def _set_marker(self, which: str) -> None:
        now = self.buffer.newest_time
        if which == "a":
            self.mark_a = now
        else:
            self.mark_b = now
        self._update_marker_label()

    def _update_marker_label(self) -> None:
        def fmt(v):
            return "--" if v is None else f"{v:.3f}"
        span = ""
        if self.mark_a is not None and self.mark_b is not None:
            span = f"   \u0394 {abs(self.mark_b - self.mark_a):.3f}s"
        self.marker_label.configure(
            text=f"a {fmt(self.mark_a)}   b {fmt(self.mark_b)}{span}")

    def _add_event(self) -> None:
        label = self.event_var.get().strip() or "event"
        t_now = self.buffer.newest_time
        self.events.append((t_now, label))
        if self.recorder.active:
            self.recorder.mark_event(label)
        self._set_status(f"logged '{label}' at {t_now:.3f}s")

    def _clear_annotations(self) -> None:
        self.events.clear()
        self.mark_a = self.mark_b = None
        self._update_marker_label()
        self._set_status("markers and events cleared")

    # ------------------------------------------------------------- saving ---

    def _toggle_record(self) -> None:
        if self.recorder.active:
            path = self.recorder.stop()
            rows = self.recorder.rows_written
            self.record_btn.set_text("\u25cf record")
            self._set_status(f"saved {rows} rows \u00b7 {path}")
            return

        path = filedialog.asksaveasfilename(
            title="record to csv", defaultextension=".csv",
            initialfile=rec.suggest_filename().replace("\\", "/").split("/")[-1],
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        note = "; ".join(f"{ui.name}={ui.filter_name.get()}" for ui in self.analog_ui)
        self.recorder.start(path, self.sample_rate, self.port_var.get(), note)
        self.record_btn.set_text("\u25a0 stop")
        self._set_status(f"recording \u00b7 {path}")

    def _save_span(self, use_markers: bool) -> None:
        if len(self.buffer) == 0:
            messagebox.showinfo("alcmaeon", "no data in the buffer yet")
            return
        if use_markers:
            if self.mark_a is None or self.mark_b is None:
                messagebox.showinfo(
                    "alcmaeon",
                    "set both markers first\n\nleft-click the plot for a, "
                    "right-click for b")
                return
            t, wall, data = self.buffer.between(self.mark_a, self.mark_b)
            note = f"span a={self.mark_a:.3f}s b={self.mark_b:.3f}s"
        else:
            t, wall, data = self.buffer.snapshot()
            note = "full scroll-back"

        if len(t) == 0:
            messagebox.showinfo("alcmaeon", "that span has scrolled out of the buffer")
            return

        path = filedialog.asksaveasfilename(
            title="save span", defaultextension=".csv",
            initialfile=rec.suggest_filename("alcmaeon_span").replace("\\", "/").split("/")[-1],
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        filters_note = "; ".join(f"{ui.name}={ui.filter_name.get()}" for ui in self.analog_ui)
        rows = rec.save_span(path, t, wall, data, self.sample_rate,
                             self.port_var.get(), self.events, f"{note}; {filters_note}")
        self._set_status(f"wrote {rows} rows ({t[-1] - t[0]:.2f}s) \u00b7 {path}")

    def _clear_buffer(self) -> None:
        self.buffer.clear()
        self._clear_annotations()
        self._set_status("buffer cleared")

    # ------------------------------------------------------------- status ---

    def _set_status(self, text: str) -> None:
        self.status_var.set(f"\u203a {text}")

    def _update_status_line(self) -> None:
        parts = []
        if self.source is None:
            parts.append("idle")
        else:
            parts.append(self.port_var.get().split(" ")[0])
            parts.append(f"{self._measured_rate:.0f} hz")
            if getattr(self.source, "bad_lines", 0):
                parts.append(f"{self.source.bad_lines} bad lines")
        parts.append(f"buffer {len(self.buffer)} "
                     f"({self.buffer.newest_time - self.buffer.oldest_time:.1f}s)")
        if self.source is not None:
            parts.append(time.strftime("%H:%M:%S"))
        if self._backdrop_name:
            parts.append(self._backdrop_name)
        if self.recorder.active:
            parts.append(f"\u25cf rec {self.recorder.rows_written}")
        if self.paused_var.get():
            parts.append("frozen")
        self.status_var.set("\u203a " + "   \u00b7   ".join(parts))

    def _on_close(self) -> None:
        if self.recorder.active:
            self.recorder.stop()
        if self.source is not None:
            self.source.stop()
        self.destroy()


def main() -> None:
    AlcmaeonApp().mainloop()


if __name__ == "__main__":
    main()
