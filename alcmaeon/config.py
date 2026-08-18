# Alcmaeon Lite -- EMG/ECG, analog and digital signal recorder
# Copyright (C) 2026  Nicolaos Eyzaguirre
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Alcmaeon Lite -- configuration
==============================

This is the file to edit first. Almost everything you would want to change
lives here: which pins map to which channel, how fast you sample, how long
the scroll-back history is, and what each channel looks like on screen.

IMPORTANT: SAMPLE_RATE_HZ, ANALOG_CHANNELS and DIGITAL_CHANNELS must match
the matching constants in arduino/alcmaeon_daq/alcmaeon_daq.ino.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Link settings
# ---------------------------------------------------------------------------

SERIAL_BAUD = 250000      # must match BAUD in the Arduino sketch
SERIAL_TIMEOUT_S = 1.0

SAMPLE_RATE_HZ = 500      # must match SAMPLE_RATE_HZ in the Arduino sketch

# ADC scaling. Uno/Nano = 10 bit (1023) at 5 V. For an ESP32 use 4095 / 3.3.
ADC_MAX_COUNTS = 1023
ADC_VREF_VOLTS = 5.0


# ---------------------------------------------------------------------------
# Channel definitions
# ---------------------------------------------------------------------------

@dataclass
class AnalogChannel:
    """One analog input, in the same order as ANALOG_PINS in the sketch."""

    name: str                       # shown in the UI and used as the CSV column
    unit: str = "V"
    zero_center: bool = False       # subtract Vref/2 (EMG/ECG boards idle mid-rail)
    default_filter: str = "Raw"     # any name from filters.PRESETS
    default_view: str = "own"
    color: str | None = None        # None -> auto colour from the theme palette


@dataclass
class DigitalChannel:
    """One digital input, in the same order as DIGITAL_PINS in the sketch."""

    name: str
    default_view: str = "overlay"   # overlay = shaded band on the signal plot
    color: str | None = None


# --- Edit these two lists to match your wiring ------------------------------

ANALOG_CHANNELS = [
    AnalogChannel("EMG",   unit="V", zero_center=True,
                  default_filter="EMG clean", default_view="overlay"),
    AnalogChannel("Pot 1", unit="V", default_filter="Smoothed",
                  default_view="own"),
    AnalogChannel("Pot 2", unit="V", default_filter="Smoothed",
                  default_view="hidden"),
]

DIGITAL_CHANNELS = [
    DigitalChannel("Button 1", default_view="overlay"),
    DigitalChannel("Button 2", default_view="hidden"),
]


# ---------------------------------------------------------------------------
# Default filter settings (all editable live in the app)
# ---------------------------------------------------------------------------

DEFAULT_HIGHPASS_HZ = 20.0     # EMG: 20 Hz.  ECG: try 0.5 Hz
DEFAULT_LOWPASS_HZ = 200.0     # keep below SAMPLE_RATE_HZ / 2
DEFAULT_NOTCH_HZ = 60.0        # 60 Hz in the Americas, 50 Hz most elsewhere
DEFAULT_NOTCH_Q = 20.0
DEFAULT_ENVELOPE_HZ = 5.0      # smoothing for the rectified EMG envelope
DEFAULT_RMS_MS = 100.0         # RMS window length
DEFAULT_SMOOTH_MS = 20.0       # moving-average window for pots


# ---------------------------------------------------------------------------
# Display / buffering
# ---------------------------------------------------------------------------

# Fast plotting: cache everything static as a bitmap and redraw only the
# traces each frame. Roughly 3x faster at default settings and more with many
# channels. The x-axis becomes "seconds ago" rather than absolute time, which
# is what lets the background stay cached.
FAST_PLOT = True

# With FAST_PLOT the y-axis only rescales when the signal actually leaves the
# current range, since every rescale costs a full redraw. Higher = calmer.
AUTOSCALE_HEADROOM = 0.45     # extra room added when rescaling, as a fraction
AUTOSCALE_INITIAL_REACH = 1.5 # how wide the very first range is set, x the signal
AUTOSCALE_MIN_INTERVAL = 2.0  # seconds between non-urgent rescales
AUTOSCALE_HALF_LIFE = 25.0    # seconds for the range to ease halfway back down
AUTOSCALE_SHRINK_AT = 0.30    # shrink only when the signal fills less than this

# Warn when the Arduino reports a different channel count than the lists above
CHECK_DEVICE_CHANNELS = True

HISTORY_SECONDS = 120        # scroll-back kept in RAM (and available to "Save span")
DEFAULT_WINDOW_SECONDS = 5   # width of the live view
WINDOW_CHOICES = [1, 2, 5, 10, 20, 30, 60]

# Backdrop line art. "random" shuffles on every launch; or name a piece from
# artwork.PIECES: parthenon, colonnade, amphora, bust, discus, ruin.
BACKDROP = "random"
BACKDROP_OPACITY = "soft"         # off | faint | soft | bold
BACKDROP_OPACITIES = {"off": 0.0, "faint": 0.11, "soft": 0.20, "bold": 0.32}

TRANSLUCENT_PLOTS = True     # let the artwork show through the graph panels

PLOT_FPS = 20                # redraw rate
POLL_MS = 20                 # how often the serial queue is drained
MAX_PLOT_POINTS = 1500       # data is decimated to this before drawing

SHOW_RAW_TRACE = True        # draw a faint unfiltered trace behind the filtered one


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

DEFAULT_SAVE_DIR = "."
CSV_FLOAT_FORMAT = "%.6f"


# ---------------------------------------------------------------------------
# Derived helpers -- no need to edit below here
# ---------------------------------------------------------------------------

N_ANALOG = len(ANALOG_CHANNELS)
N_DIGITAL = len(DIGITAL_CHANNELS)

VIEW_MODES = ["own", "overlay", "hidden"]


def _infer_channel(name: str) -> AnalogChannel:
    """Best guess at settings for a channel we have never seen before."""
    lowered = name.lower()
    biopotential = any(word in lowered for word in
                       ("emg", "ecg", "ekg", "eeg", "muscle", "biceps",
                        "tricep", "forearm", "heart"))
    return AnalogChannel(
        name,
        zero_center=biopotential,
        default_filter="EMG clean" if biopotential else "Smoothed",
        default_view="overlay" if biopotential else "own",
    )


def current_layout():
    """Snapshot the channel lists so they can be put back later."""
    return (list(ANALOG_CHANNELS), list(DIGITAL_CHANNELS))


def apply_layout(analog_names, digital_names) -> None:
    """Reshape the app around a different set of channels at runtime.

    Used when opening a recording made with different hardware: the file lists
    its own channels, so the app can follow it rather than refusing to open.
    Settings for channels whose names we already know are kept.
    """
    global ANALOG_CHANNELS, DIGITAL_CHANNELS, N_ANALOG, N_DIGITAL
    known_analog = {c.name: c for c in ANALOG_CHANNELS}
    known_digital = {c.name: c for c in DIGITAL_CHANNELS}
    ANALOG_CHANNELS = [known_analog.get(name) or _infer_channel(name)
                       for name in analog_names]
    DIGITAL_CHANNELS = [known_digital.get(name) or DigitalChannel(name, "own")
                        for name in digital_names]
    N_ANALOG = len(ANALOG_CHANNELS)
    N_DIGITAL = len(DIGITAL_CHANNELS)


def apply_layout_spec(analog, digital) -> None:
    """Set the channels from full descriptions rather than just names.

    Used by the in-app channel editor and by the saved settings file, so a
    user never has to edit this file to add an input.
    """
    global ANALOG_CHANNELS, DIGITAL_CHANNELS, N_ANALOG, N_DIGITAL
    ANALOG_CHANNELS = [
        AnalogChannel(
            entry.get("name") or f"Analog {i + 1}",
            unit=entry.get("unit", "V"),
            zero_center=bool(entry.get("zero_center", False)),
            default_filter=entry.get("filter", "Raw"),
            default_view=entry.get("view", "own"),
        )
        for i, entry in enumerate(analog)
    ]
    DIGITAL_CHANNELS = [
        DigitalChannel(entry.get("name") or f"Digital {j + 1}",
                       default_view=entry.get("view", "overlay"))
        for j, entry in enumerate(digital)
    ]
    N_ANALOG = len(ANALOG_CHANNELS)
    N_DIGITAL = len(DIGITAL_CHANNELS)


def restore_layout(layout) -> None:
    """Put back a layout captured by current_layout()."""
    global ANALOG_CHANNELS, DIGITAL_CHANNELS, N_ANALOG, N_DIGITAL
    ANALOG_CHANNELS, DIGITAL_CHANNELS = list(layout[0]), list(layout[1])
    N_ANALOG = len(ANALOG_CHANNELS)
    N_DIGITAL = len(DIGITAL_CHANNELS)


def counts_to_volts(counts: float, channel: AnalogChannel) -> float:
    """Convert a raw ADC reading to volts for one channel."""
    volts = counts * (ADC_VREF_VOLTS / ADC_MAX_COUNTS)
    if channel.zero_center:
        volts -= ADC_VREF_VOLTS / 2.0
    return volts


def csv_columns() -> list[str]:
    """Column names for saved files, matching the ring-buffer layout."""
    cols = ["iso_time", "t_seconds", "device_seconds"]
    cols += [f"{c.name}_raw" for c in ANALOG_CHANNELS]
    cols += [f"{c.name}_filtered" for c in ANALOG_CHANNELS]
    cols += [c.name for c in DIGITAL_CHANNELS]
    cols += ["event"]
    return cols
