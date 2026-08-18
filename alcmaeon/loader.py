"""
Alcmaeon Lite -- loading saved recordings
=========================================

Reads back the CSV files this app writes, so a session can be reopened,
scrubbed through and analysed long after the hardware is unplugged.

The format is the one produced by recorder.py:

    # comment lines carrying the metadata
    iso_time, t_seconds, device_seconds,
    <ch>_raw..., <ch>_filtered..., <button>..., event
"""

from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass, field

import numpy as np

from . import config as cfg


@dataclass
class Recording:
    """One loaded file, in the same column layout as the live ring buffer."""

    path: str
    t: np.ndarray                       # seconds, relative to the recording start
    wall: np.ndarray                    # unix epoch seconds
    data: np.ndarray                    # (n, 2*n_analog + n_digital)
    events: list[tuple[float, str]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    analog_names: list[str] = field(default_factory=list)
    digital_names: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return float(self.t[-1] - self.t[0]) if self.t.size else 0.0

    @property
    def sample_rate(self) -> float:
        """Measured from the timestamps, not trusted from the header."""
        if self.t.size < 2 or self.duration <= 0:
            return float(self.meta.get("sample_rate_hz", cfg.SAMPLE_RATE_HZ) or 0)
        return (self.t.size - 1) / self.duration

    def summary(self) -> str:
        return (f"{self.t.size} samples \u00b7 {self.duration:.2f}s \u00b7 "
                f"{self.sample_rate:.0f} hz")

    def matches(self) -> bool:
        """True if this file's channels are the ones the app is set up for."""
        return (self.analog_names == [c.name for c in cfg.ANALOG_CHANNELS]
                and self.digital_names == [c.name for c in cfg.DIGITAL_CHANNELS])


class LoadError(Exception):
    """Raised with a message meant to be shown to the user as-is."""


def load_recording(path: str) -> Recording:
    """Read a CSV written by this app. Raises LoadError with a plain message."""
    meta: dict[str, str] = {}
    rows: list[list[str]] = []
    header: list[str] | None = None

    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.startswith("#"):
                    if ":" in line:
                        key, _, value = line[1:].partition(":")
                        meta[key.strip()] = value.strip()
                    continue
                if not line.strip():
                    continue
                fields = next(csv.reader([line]))
                if header is None:
                    header = [f.strip() for f in fields]
                else:
                    rows.append(fields)
    except OSError as exc:
        raise LoadError(f"could not open the file:\n{exc}") from exc

    if header is None:
        raise LoadError("this file has no header row \u2014 is it an "
                        "Alcmaeon Lite recording?")
    if not rows:
        raise LoadError("this file has a header but no data in it")

    analog = [c[:-4] for c in header if c.endswith("_raw")]
    digital = _digital_columns(header, analog)
    if not analog:
        raise LoadError("no '<channel>_raw' columns found \u2014 this does not "
                        "look like an Alcmaeon Lite recording")

    # A file that carries different channels than the app is currently set up
    # for is not an error: it names its own channels, so the caller can adopt
    # them (see config.apply_layout) rather than refusing to open it.

    index = {name: i for i, name in enumerate(header)}
    t_col = index.get("t_seconds", index.get("device_seconds", 1))
    iso_col = index.get("iso_time", 0)
    event_col = index.get("event")
    raw_cols = [index[f"{name}_raw"] for name in analog]
    filt_cols = [index.get(f"{name}_filtered", index[f"{name}_raw"]) for name in analog]
    digital_cols = [index[name] for name in digital]

    n = len(rows)
    t = np.zeros(n, dtype=np.float64)
    wall = np.zeros(n, dtype=np.float64)
    data = np.zeros((n, 2 * len(analog) + len(digital)), dtype=np.float32)
    events: list[tuple[float, str]] = []

    bad = 0
    for i, row in enumerate(rows):
        try:
            t[i] = float(row[t_col])
            for j, col in enumerate(raw_cols):
                data[i, j] = float(row[col])
            for j, col in enumerate(filt_cols):
                data[i, len(analog) + j] = float(row[col])
            for j, col in enumerate(digital_cols):
                data[i, 2 * len(analog) + j] = float(row[col])
        except (ValueError, IndexError):
            bad += 1
            continue
        wall[i] = _parse_iso(row[iso_col]) if iso_col < len(row) else 0.0
        if event_col is not None and event_col < len(row) and row[event_col].strip():
            events.append((t[i], row[event_col].strip()))

    if bad == n:
        raise LoadError("none of the rows could be read as numbers")

    return Recording(path=path, t=t, wall=wall, data=data, events=events,
                     meta=meta, analog_names=analog, digital_names=digital)


def _digital_columns(header: list[str], analog: list[str]) -> list[str]:
    """Everything between the last _filtered column and 'event'."""
    known = {"iso_time", "t_seconds", "device_seconds", "event"}
    known |= {f"{a}_raw" for a in analog} | {f"{a}_filtered" for a in analog}
    return [c for c in header if c not in known]


def _parse_iso(text: str) -> float:
    try:
        return _dt.datetime.fromisoformat(text.strip()).timestamp()
    except (ValueError, AttributeError):
        return 0.0
