"""
Alcmaeon Lite -- analysis
=========================

Measurements over a span of data: the standard EMG amplitude and frequency
metrics, plus contraction detection and button statistics.

Everything here is plain numpy on arrays, with no reference to the GUI, so it
is easy to reuse in a script:

    from alcmaeon import loader, analysis
    rec = loader.load_recording("session.csv")
    report = analysis.analyse(rec.t, rec.data)
    print(analysis.format_report(report))
"""

from __future__ import annotations

import numpy as np

from . import config as cfg


# ---------------------------------------------------------------------------
# Individual measurements
# ---------------------------------------------------------------------------

def rms(x: np.ndarray) -> float:
    """Root mean square -- the usual measure of EMG amplitude."""
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def mav(x: np.ndarray) -> float:
    """Mean absolute value: the other standard amplitude measure."""
    return float(np.mean(np.abs(x))) if x.size else 0.0


def zero_crossings(x: np.ndarray, deadzone: float = 0.0) -> int:
    """Sign changes, ignoring wobble inside a deadzone. Rises with fatigue."""
    if x.size < 2:
        return 0
    keep = np.abs(x) > deadzone
    signal = x[keep]
    if signal.size < 2:
        return 0
    return int(np.count_nonzero(np.diff(np.signbit(signal))))


def spectrum(x: np.ndarray, fs: float):
    """One-sided power spectrum of a detrended signal."""
    if x.size < 8 or fs <= 0:
        return np.zeros(0), np.zeros(0)
    centred = x - float(np.mean(x))
    window = np.hanning(centred.size)
    power = np.abs(np.fft.rfft(centred * window)) ** 2
    freqs = np.fft.rfftfreq(centred.size, d=1.0 / fs)
    return freqs, power


def median_frequency(freqs: np.ndarray, power: np.ndarray) -> float:
    """Frequency splitting the spectrum into equal halves of power.

    The classic muscle-fatigue indicator: it drifts downward as a muscle
    tires, usually well before the amplitude changes.
    """
    if power.size == 0:
        return 0.0
    total = np.cumsum(power)
    if total[-1] <= 0:
        return 0.0
    return float(freqs[int(np.searchsorted(total, total[-1] / 2.0))])


def mean_frequency(freqs: np.ndarray, power: np.ndarray) -> float:
    if power.size == 0 or power.sum() <= 0:
        return 0.0
    return float(np.sum(freqs * power) / np.sum(power))


def envelope(x: np.ndarray, fs: float, window_ms: float = 100.0) -> np.ndarray:
    """Rectify and box-smooth -- the activation curve."""
    width = max(1, int(round(fs * window_ms / 1000.0)))
    rectified = np.abs(x)
    kernel = np.ones(width) / width
    return np.convolve(rectified, kernel, mode="same")


def find_contractions(x: np.ndarray, t: np.ndarray, fs: float,
                      threshold_fraction: float = 0.20,
                      min_duration_s: float = 0.10) -> list[dict]:
    """Detect bursts of activity in a signal.

    A sample counts as active when the envelope rises above a threshold set
    between the resting level and the peak. Runs shorter than min_duration_s
    are discarded as noise.
    """
    if x.size < 4:
        return []
    env = envelope(x, fs)
    rest = float(np.percentile(env, 10))
    peak = float(np.max(env))
    if peak <= rest:
        return []
    threshold = rest + threshold_fraction * (peak - rest)

    active = env > threshold
    edges = np.diff(active.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if active[0]:
        starts.insert(0, 0)
    if active[-1]:
        ends.append(active.size - 1)

    bursts = []
    for start, end in zip(starts, ends):
        duration = float(t[end] - t[start])
        if duration < min_duration_s:
            continue
        segment = x[start:end + 1]
        bursts.append({
            "start": float(t[start]),
            "end": float(t[end]),
            "duration": duration,
            "peak": float(np.max(env[start:end + 1])),
            "rms": rms(segment),
        })
    return bursts


def button_stats(states: np.ndarray, t: np.ndarray) -> dict:
    """Press count, total on-time and duty cycle for a digital channel."""
    if states.size == 0:
        return {"presses": 0, "on_time": 0.0, "duty": 0.0, "mean_press": 0.0}
    high = states > 0.5
    edges = np.diff(high.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if high[0]:
        starts.insert(0, 0)
    if high[-1]:
        ends.append(high.size - 1)

    durations = [float(t[e] - t[s]) for s, e in zip(starts, ends)]
    span = float(t[-1] - t[0]) or 1.0
    on_time = float(sum(durations))
    return {
        "presses": len(durations),
        "on_time": on_time,
        "duty": 100.0 * on_time / span,
        "mean_press": (on_time / len(durations)) if durations else 0.0,
    }


# ---------------------------------------------------------------------------
# Whole-span report
# ---------------------------------------------------------------------------

def analyse(t: np.ndarray, data: np.ndarray, fs: float | None = None,
            label: str = "") -> dict:
    """Measure every channel over the given span."""
    n_analog, n_digital = cfg.N_ANALOG, cfg.N_DIGITAL
    duration = float(t[-1] - t[0]) if t.size > 1 else 0.0
    if fs is None or fs <= 0:
        fs = (t.size - 1) / duration if duration > 0 else float(cfg.SAMPLE_RATE_HZ)

    report: dict = {
        "label": label,
        "samples": int(t.size),
        "duration": duration,
        "sample_rate": fs,
        "start": float(t[0]) if t.size else 0.0,
        "end": float(t[-1]) if t.size else 0.0,
        "analog": [],
        "digital": [],
    }

    for i, channel in enumerate(cfg.ANALOG_CHANNELS):
        raw = data[:, i].astype(np.float64)
        filtered = data[:, n_analog + i].astype(np.float64)
        freqs, power = spectrum(filtered, fs)
        entry = {
            "name": channel.name,
            "unit": channel.unit,
            "mean": float(np.mean(filtered)) if filtered.size else 0.0,
            "std": float(np.std(filtered)) if filtered.size else 0.0,
            "min": float(np.min(filtered)) if filtered.size else 0.0,
            "max": float(np.max(filtered)) if filtered.size else 0.0,
            "p2p": float(np.ptp(filtered)) if filtered.size else 0.0,
            "rms": rms(filtered),
            "mav": mav(filtered),
            "raw_p2p": float(np.ptp(raw)) if raw.size else 0.0,
            "zero_crossings": zero_crossings(filtered, deadzone=0.01 * rms(filtered)),
            "median_freq": median_frequency(freqs, power),
            "mean_freq": mean_frequency(freqs, power),
            # Contraction detection only makes sense for a biopotential
            # channel. zero_center marks those in config.py; a pot sweeping
            # slowly would otherwise report one enormous "contraction".
            "is_biopotential": bool(channel.zero_center),
            "contractions": (find_contractions(filtered, t, fs)
                             if channel.zero_center else []),
        }
        entry["zc_rate"] = entry["zero_crossings"] / duration if duration > 0 else 0.0
        report["analog"].append(entry)

    for j, channel in enumerate(cfg.DIGITAL_CHANNELS):
        entry = button_stats(data[:, 2 * n_analog + j], t)
        entry["name"] = channel.name
        report["digital"].append(entry)

    return report


def format_report(report: dict) -> str:
    """Render the measurements as fixed-width text."""
    out: list[str] = []
    add = out.append

    add("=" * 62)
    add("  ALCMAEON LITE \u00b7 ANALYSIS")
    if report.get("label"):
        add(f"  {report['label']}")
    add("=" * 62)
    add("")
    add(f"  span          {report['start']:.3f}s \u2192 {report['end']:.3f}s")
    add(f"  duration      {report['duration']:.3f} s")
    add(f"  samples       {report['samples']}")
    add(f"  sample rate   {report['sample_rate']:.1f} Hz  (measured)")
    add("")

    for channel in report["analog"]:
        unit = channel["unit"]
        add("-" * 62)
        add(f"  {channel['name'].upper()}   (filtered signal)")
        add("-" * 62)
        add(f"    rms                 {channel['rms']:10.5f} {unit}")
        add(f"    mean abs value      {channel['mav']:10.5f} {unit}")
        add(f"    peak to peak        {channel['p2p']:10.5f} {unit}")
        add(f"    min / max           {channel['min']:10.5f} / "
            f"{channel['max']:.5f} {unit}")
        add(f"    mean / std          {channel['mean']:10.5f} / "
            f"{channel['std']:.5f} {unit}")
        add(f"    raw peak to peak    {channel['raw_p2p']:10.5f} {unit}")
        add("")
        fatigue_note = "     (drops as a muscle fatigues)" \
            if channel.get("is_biopotential") else ""
        add(f"    median frequency    {channel['median_freq']:10.1f} Hz"
            + fatigue_note)
        add(f"    mean frequency      {channel['mean_freq']:10.1f} Hz")
        add(f"    zero crossings      {channel['zero_crossings']:10d}"
            f"        ({channel['zc_rate']:.0f}/s)")
        add("")

        if not channel.get("is_biopotential"):
            continue

        bursts = channel["contractions"]
        add(f"    contractions detected: {len(bursts)}")
        if bursts:
            mean_dur = sum(b["duration"] for b in bursts) / len(bursts)
            add(f"      mean duration     {mean_dur:10.3f} s")
            add(f"      strongest         {max(b['rms'] for b in bursts):10.5f} "
                f"{unit} rms")
            add("")
            add("        #      start        end   duration     rms")
            for k, burst in enumerate(bursts[:15], start=1):
                add(f"      {k:3d}  {burst['start']:9.3f}  {burst['end']:9.3f}  "
                    f"{burst['duration']:9.3f}  {burst['rms']:8.5f}")
            if len(bursts) > 15:
                add(f"      \u2026 and {len(bursts) - 15} more")
        add("")

    if report["digital"]:
        add("-" * 62)
        add("  BUTTONS")
        add("-" * 62)
        for channel in report["digital"]:
            add(f"    {channel['name']}")
            add(f"      presses           {channel['presses']:10d}")
            add(f"      total on time     {channel['on_time']:10.3f} s")
            add(f"      mean press        {channel['mean_press']:10.3f} s")
            add(f"      duty cycle        {channel['duty']:10.1f} %")
        add("")

    add("=" * 62)
    return "\n".join(out)
