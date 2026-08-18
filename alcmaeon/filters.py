"""
Alcmaeon Lite -- filters
========================

Real-time, one-sample-at-a-time filters. No SciPy needed: the biquad
coefficients come from the classic Robert Bristow-Johnson "audio EQ cookbook"
formulas, which are the same maths as a 2nd-order Butterworth when Q = 0.7071.

Every stage implements the same tiny interface::

    stage.process(x) -> y      # one sample in, one sample out
    stage.reset()              # clear internal state

A FilterChain just runs several stages back to back. To add your own filter,
write a class with those two methods and reference it in build_chain().
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Stage base + building blocks
# ---------------------------------------------------------------------------

class Stage:
    """Base class for a single processing step."""

    def process(self, x: float) -> float:      # pragma: no cover - overridden
        return x

    def reset(self) -> None:
        pass


class Biquad(Stage):
    """Second-order IIR section, transposed direct form II."""

    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float):
        self.b0, self.b1, self.b2 = b0, b1, b2
        self.a1, self.a2 = a1, a2
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x: float) -> float:
        y = self.b0 * x + self.z1
        self.z1 = self.b1 * x - self.a1 * y + self.z2
        self.z2 = self.b2 * x - self.a2 * y
        return y

    def reset(self) -> None:
        self.z1 = self.z2 = 0.0


def _clamp_freq(fs: float, fc: float) -> float:
    """Keep a cutoff strictly inside (0, Nyquist) so the design never blows up."""
    return max(0.05, min(fc, 0.45 * fs))


def lowpass(fs: float, fc: float, q: float = 0.70710678) -> Biquad:
    w0 = 2.0 * math.pi * _clamp_freq(fs, fc) / fs
    cos_w0, alpha = math.cos(w0), math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    return Biquad(((1 - cos_w0) / 2) / a0, (1 - cos_w0) / a0, ((1 - cos_w0) / 2) / a0,
                  (-2 * cos_w0) / a0, (1 - alpha) / a0)


def highpass(fs: float, fc: float, q: float = 0.70710678) -> Biquad:
    w0 = 2.0 * math.pi * _clamp_freq(fs, fc) / fs
    cos_w0, alpha = math.cos(w0), math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    return Biquad(((1 + cos_w0) / 2) / a0, (-(1 + cos_w0)) / a0, ((1 + cos_w0) / 2) / a0,
                  (-2 * cos_w0) / a0, (1 - alpha) / a0)


def notch(fs: float, fc: float, q: float = 20.0) -> Biquad:
    """Band-stop for mains hum. Higher Q = narrower notch."""
    w0 = 2.0 * math.pi * _clamp_freq(fs, fc) / fs
    cos_w0, alpha = math.cos(w0), math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    return Biquad(1.0 / a0, (-2 * cos_w0) / a0, 1.0 / a0,
                  (-2 * cos_w0) / a0, (1 - alpha) / a0)


class DCBlock(Stage):
    """One-pole high-pass -- removes electrode offset without touching the shape."""

    def __init__(self, fs: float, fc: float = 0.5):
        self.r = math.exp(-2.0 * math.pi * _clamp_freq(fs, fc) / fs)
        self.x1 = 0.0
        self.y1 = 0.0

    def process(self, x: float) -> float:
        y = x - self.x1 + self.r * self.y1
        self.x1, self.y1 = x, y
        return y

    def reset(self) -> None:
        self.x1 = self.y1 = 0.0


class Rectify(Stage):
    """Full-wave rectifier: |x|."""

    def process(self, x: float) -> float:
        return abs(x)


class MovingAverage(Stage):
    """Boxcar smoother over `n` samples."""

    def __init__(self, n: int):
        self.n = max(1, int(n))
        self.buf: deque[float] = deque(maxlen=self.n)
        self.total = 0.0

    def process(self, x: float) -> float:
        if len(self.buf) == self.n:
            self.total -= self.buf[0]
        self.buf.append(x)
        self.total += x
        return self.total / len(self.buf)

    def reset(self) -> None:
        self.buf.clear()
        self.total = 0.0


class RMSWindow(Stage):
    """Sliding-window RMS -- the standard EMG activation measure."""

    def __init__(self, n: int):
        self.n = max(1, int(n))
        self.buf: deque[float] = deque(maxlen=self.n)
        self.total = 0.0

    def process(self, x: float) -> float:
        sq = x * x
        if len(self.buf) == self.n:
            self.total -= self.buf[0]
        self.buf.append(sq)
        self.total += sq
        return math.sqrt(max(0.0, self.total / len(self.buf)))

    def reset(self) -> None:
        self.buf.clear()
        self.total = 0.0


class Gain(Stage):
    """Simple scaler -- handy for putting a pot on the same axis as the EMG."""

    def __init__(self, gain: float = 1.0):
        self.gain = gain

    def process(self, x: float) -> float:
        return x * self.gain


class FilterChain:
    """An ordered list of stages applied to every incoming sample."""

    def __init__(self, name: str = "Raw", stages: list[Stage] | None = None):
        self.name = name
        self.stages: list[Stage] = stages or []

    def process(self, x: float) -> float:
        for stage in self.stages:
            x = stage.process(x)
        return x

    def reset(self) -> None:
        for stage in self.stages:
            stage.reset()


# ---------------------------------------------------------------------------
# Settings + presets
# ---------------------------------------------------------------------------

@dataclass
class FilterSettings:
    """Live values from the "Filter settings" panel."""

    fs: float = 500.0
    highpass_hz: float = 20.0
    lowpass_hz: float = 200.0
    notch_hz: float = 60.0
    notch_q: float = 20.0
    envelope_hz: float = 5.0
    rms_ms: float = 100.0
    smooth_ms: float = 20.0

    def samples(self, milliseconds: float) -> int:
        return max(1, int(round(self.fs * milliseconds / 1000.0)))


# Order shown in the per-channel dropdowns.
PRESETS = [
    "Raw",
    "DC block",
    "Low-pass",
    "High-pass",
    "Band-pass",
    "Notch",
    "EMG clean",
    "Envelope",
    "RMS",
    "Smoothed",
]

PRESET_HELP = {
    "Raw":        "No processing at all.",
    "DC block":   "Removes electrode/offset drift only.",
    "Low-pass":   "Keeps everything below the low-pass cutoff.",
    "High-pass":  "Keeps everything above the high-pass cutoff.",
    "Band-pass":  "High-pass then low-pass (the usual EMG 20-450 Hz band).",
    "Notch":      "Removes mains hum at the notch frequency.",
    "EMG clean":  "Band-pass + notch at the mains frequency and its 2nd harmonic.",
    "Envelope":   "EMG clean, rectified, then smoothed -- the muscle activation curve.",
    "RMS":        "EMG clean, then sliding-window RMS.",
    "Smoothed":   "Moving average. Good for potentiometers.",
}


def build_chain(preset: str, s: FilterSettings) -> FilterChain:
    """Turn a preset name + settings into a ready-to-use FilterChain.

    To add a preset: append the name to PRESETS and add a branch here.
    """
    stages: list[Stage] = []

    if preset == "Raw":
        pass
    elif preset == "DC block":
        stages = [DCBlock(s.fs, 0.5)]
    elif preset == "Low-pass":
        stages = [lowpass(s.fs, s.lowpass_hz)]
    elif preset == "High-pass":
        stages = [highpass(s.fs, s.highpass_hz)]
    elif preset == "Band-pass":
        stages = [highpass(s.fs, s.highpass_hz), lowpass(s.fs, s.lowpass_hz)]
    elif preset == "Notch":
        stages = [notch(s.fs, s.notch_hz, s.notch_q)]
    elif preset == "EMG clean":
        stages = _emg_clean(s)
    elif preset == "Envelope":
        stages = _emg_clean(s) + [Rectify(),
                                  lowpass(s.fs, s.envelope_hz),
                                  lowpass(s.fs, s.envelope_hz)]
    elif preset == "RMS":
        stages = _emg_clean(s) + [RMSWindow(s.samples(s.rms_ms))]
    elif preset == "Smoothed":
        stages = [MovingAverage(s.samples(s.smooth_ms))]
    else:
        raise ValueError(f"Unknown filter preset: {preset!r}")

    return FilterChain(preset, stages)


def _emg_clean(s: FilterSettings) -> list[Stage]:
    """Band-pass plus mains notch (and its 2nd harmonic if it fits below Nyquist)."""
    stages: list[Stage] = [
        highpass(s.fs, s.highpass_hz),
        notch(s.fs, s.notch_hz, s.notch_q),
    ]
    if s.notch_hz * 2 < 0.45 * s.fs:
        stages.append(notch(s.fs, s.notch_hz * 2, s.notch_q))
    stages.append(lowpass(s.fs, s.lowpass_hz))
    return stages
