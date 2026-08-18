"""
Alcmaeon Lite -- ring buffer
============================

A fixed-size numpy ring buffer holding the last HISTORY_SECONDS of data.
It feeds both the live plot and the "save this span" feature, so nothing has
to be re-read from disk and memory use is constant no matter how long the
session runs.
"""

from __future__ import annotations

import numpy as np


class RingBuffer:
    """Circular store of (time, wall-clock, values[]) rows."""

    def __init__(self, capacity: int, n_columns: int):
        self.capacity = int(capacity)
        self.n_columns = int(n_columns)
        self.t = np.zeros(self.capacity, dtype=np.float64)        # seconds since start
        self.wall = np.zeros(self.capacity, dtype=np.float64)     # unix epoch seconds
        self.data = np.zeros((self.capacity, self.n_columns), dtype=np.float32)
        self._write = 0
        self._count = 0

    # -- writing ------------------------------------------------------------

    def append(self, t: float, wall: float, values) -> None:
        i = self._write
        self.t[i] = t
        self.wall[i] = wall
        self.data[i, :] = values
        self._write = (i + 1) % self.capacity
        self._count = min(self._count + 1, self.capacity)

    def fill(self, t, wall, data) -> None:
        """Load a whole dataset at once (used when opening a saved file).

        Much faster than appending row by row, which matters for long
        recordings: a 10 minute session at 500 Hz is 300,000 rows.
        """
        import numpy as _np
        count = min(len(t), self.capacity)
        self.t[:count] = _np.asarray(t[-count:], dtype=_np.float64)
        self.wall[:count] = _np.asarray(wall[-count:], dtype=_np.float64)
        self.data[:count, :] = _np.asarray(data[-count:], dtype=_np.float32)
        self._count = count
        self._write = count % self.capacity

    def clear(self) -> None:
        self._write = 0
        self._count = 0

    # -- reading ------------------------------------------------------------

    def __len__(self) -> int:
        return self._count

    @property
    def newest_time(self) -> float:
        if self._count == 0:
            return 0.0
        return float(self.t[(self._write - 1) % self.capacity])

    @property
    def oldest_time(self) -> float:
        if self._count == 0:
            return 0.0
        start = (self._write - self._count) % self.capacity
        return float(self.t[start])

    def _ordered_index(self) -> np.ndarray:
        start = (self._write - self._count) % self.capacity
        return (np.arange(self._count) + start) % self.capacity

    def snapshot(self):
        """All stored rows, oldest first: (t, wall, data)."""
        idx = self._ordered_index()
        return self.t[idx], self.wall[idx], self.data[idx]

    def last_seconds(self, seconds: float):
        """The most recent `seconds` of data, oldest first."""
        t, wall, data = self.snapshot()
        if t.size == 0:
            return t, wall, data
        cutoff = t[-1] - seconds
        keep = np.searchsorted(t, cutoff, side="left")
        return t[keep:], wall[keep:], data[keep:]

    def between(self, t0: float, t1: float):
        """Everything between two timestamps, inclusive, oldest first."""
        t, wall, data = self.snapshot()
        if t.size == 0:
            return t, wall, data
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        a = np.searchsorted(t, lo, side="left")
        b = np.searchsorted(t, hi, side="right")
        return t[a:b], wall[a:b], data[a:b]


def decimate(t: np.ndarray, y: np.ndarray, max_points: int):
    """Reduce a trace for drawing while keeping its peaks.

    Taking every Nth sample is fast but destroys exactly what matters in a
    biosignal: a spike between two kept samples disappears. Worse, as the live
    window slides the kept indices shift, so the same recorded spike is drawn
    one frame and dropped the next -- it flickers even though the data never
    changed.

    Instead each bucket contributes its minimum and its maximum, in the order
    they occurred, so no peak is ever lost and the envelope stays put. Bucket
    edges are anchored to absolute time rather than to the start of the window,
    so the grouping does not shift as data scrolls past. This is what a digital
    oscilloscope does.

    Pass absolute timestamps, not window-relative ones, or the anchoring
    cannot work.
    """
    n = t.size
    if n <= max_points or max_points < 4:
        return t, y

    buckets = max(2, max_points // 2)          # every bucket yields two points
    step = int(np.ceil(n / buckets))
    if step < 2:
        return t, y

    dt = (t[-1] - t[0]) / (n - 1) if n > 1 else 0.0
    start = 0
    if dt > 0:
        # align the first bucket to an absolute multiple of the bucket width
        phase = int(round(t[0] / dt)) % step
        start = (step - phase) % step
        if start >= n:
            start = 0

    body_t, body_y = t[start:], y[start:]
    whole = (body_y.size // step) * step
    if whole == 0:
        return t, y

    grid_t = body_t[:whole].reshape(-1, step)
    grid_y = body_y[:whole].reshape(-1, step)
    lows = grid_y.min(axis=1)
    highs = grid_y.max(axis=1)
    low_first = grid_y.argmin(axis=1) <= grid_y.argmax(axis=1)

    count = lows.size
    out_y = np.empty(count * 2, dtype=y.dtype)
    out_t = np.empty(count * 2, dtype=t.dtype)
    out_y[0::2] = np.where(low_first, lows, highs)
    out_y[1::2] = np.where(low_first, highs, lows)
    out_t[0::2] = grid_t[:, 0]
    out_t[1::2] = grid_t[:, 0] + dt * (step * 0.5)

    # keep the samples either side of the buckets so the trace still reaches
    # both edges of the view
    head_t, head_y = t[:start], y[:start]
    tail_t, tail_y = body_t[whole:], body_y[whole:]
    if head_t.size or tail_t.size:
        out_t = np.concatenate((head_t, out_t, tail_t))
        out_y = np.concatenate((head_y, out_y, tail_y))
    return out_t, out_y
