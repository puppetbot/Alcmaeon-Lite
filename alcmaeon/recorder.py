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
Alcmaeon Lite -- recording
==========================

Two ways to get data onto disk:

1. Recorder      -- streams every sample straight to a CSV while you record,
                    so a long session never eats RAM and a crash loses nothing.
2. save_span()   -- exports an arbitrary window (markers A -> B, or the whole
                    scroll-back) out of the in-memory ring buffer.

Both write the same columns, described by config.csv_columns():

    iso_time, t_seconds, device_seconds, <ch>_raw..., <ch>_filtered...,
    <button>..., event

`iso_time` is host wall-clock (ISO 8601, local time with UTC offset) and
`device_seconds` is the Arduino's own micros() clock, which is the one to trust
for sample spacing.
"""

from __future__ import annotations

import csv
import datetime as _dt
import os

from . import config as cfg


def iso(wall_seconds: float) -> str:
    """Unix epoch seconds -> local ISO 8601 timestamp with milliseconds."""
    return _dt.datetime.fromtimestamp(wall_seconds).astimezone().isoformat(
        timespec="milliseconds")


def _metadata_lines(sample_rate: float, source: str, note: str = "") -> list[str]:
    return [
        f"# Alcmaeon Lite recording",
        f"# saved_at: {iso(_dt.datetime.now().timestamp())}",
        f"# source: {source}",
        f"# sample_rate_hz: {sample_rate}",
        f"# adc: {cfg.ADC_MAX_COUNTS} counts @ {cfg.ADC_VREF_VOLTS} V",
        f"# analog_channels: {', '.join(c.name for c in cfg.ANALOG_CHANNELS)}",
        f"# digital_channels: {', '.join(c.name for c in cfg.DIGITAL_CHANNELS)}",
        f"# note: {note}",
    ]


class Recorder:
    """Append-as-you-go CSV writer."""

    def __init__(self):
        self.path: str | None = None
        self._fh = None
        self._writer = None
        self.rows_written = 0
        self._pending_event = ""

    @property
    def active(self) -> bool:
        return self._fh is not None

    def start(self, path: str, sample_rate: float, source: str,
              filters_note: str = "") -> None:
        self.stop()
        self._fh = open(path, "w", newline="", encoding="utf-8")
        for line in _metadata_lines(sample_rate, source, filters_note):
            self._fh.write(line + "\n")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(cfg.csv_columns())
        self.path = path
        self.rows_written = 0

    def mark_event(self, label: str) -> None:
        """Attach a label to the next row written."""
        self._pending_event = label

    def write(self, t: float, wall: float, values) -> None:
        if self._writer is None:
            return
        row = [iso(wall), f"{t:.6f}", f"{t:.6f}"]
        row += [format(float(v), ".6f") for v in values[:2 * cfg.N_ANALOG]]
        row += [str(int(v)) for v in values[2 * cfg.N_ANALOG:]]
        row.append(self._pending_event)
        self._pending_event = ""
        self._writer.writerow(row)
        self.rows_written += 1

    def stop(self) -> str | None:
        path = self.path
        if self._fh is not None:
            if self._pending_event:
                # An event logged in the same instant recording stopped never
                # reached a data row. Keep it rather than losing it silently.
                self._fh.write(f"# unflushed_event: {self._pending_event}\n")
                self._pending_event = ""
            self._fh.close()
        self._fh = None
        self._writer = None
        self.path = None
        return path


def save_span(path: str, t_array, wall_array, data_array,
              sample_rate: float, source: str, events=None,
              note: str = "") -> int:
    """Write a slice of the ring buffer to CSV. Returns the row count.

    `events` is an iterable of (time_seconds, label); each one is attached to
    the nearest sample in the exported range.
    """
    events = list(events or [])
    n = len(t_array)

    # Map each event onto its closest row index.
    event_at: dict[int, str] = {}
    for t_event, label in events:
        if n == 0:
            break
        if t_array[0] <= t_event <= t_array[-1]:
            idx = int(min(range(n), key=lambda i: abs(t_array[i] - t_event)))
            event_at[idx] = (event_at.get(idx, "") + " | " + label).strip(" |")

    with open(path, "w", newline="", encoding="utf-8") as fh:
        for line in _metadata_lines(sample_rate, source, note):
            fh.write(line + "\n")
        if n:
            fh.write(f"# span_seconds: {t_array[0]:.6f} to {t_array[-1]:.6f}\n")
        writer = csv.writer(fh)
        writer.writerow(cfg.csv_columns())
        for i in range(n):
            values = data_array[i]
            row = [iso(float(wall_array[i])), f"{float(t_array[i]):.6f}",
                   f"{float(t_array[i]):.6f}"]
            row += [format(float(v), ".6f") for v in values[:2 * cfg.N_ANALOG]]
            row += [str(int(v)) for v in values[2 * cfg.N_ANALOG:]]
            row.append(event_at.get(i, ""))
            writer.writerow(row)
    return n


def suggest_filename(prefix: str = "alcmaeon", directory: str | None = None) -> str:
    """Timestamped default filename, e.g. alcmaeon_2026-08-16_143012.csv"""
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = f"{prefix}_{stamp}.csv"
    return os.path.join(directory or cfg.DEFAULT_SAVE_DIR, name)
