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
Alcmaeon Lite -- acquisition
============================

Two interchangeable data sources, both of which push `Sample` objects onto a
thread-safe queue that the GUI drains:

* SerialSource     -- reads CSV lines from the Arduino.
* SimulatedSource  -- fabricates plausible EMG bursts, pot sweeps and button
                      presses so you can develop and demo with no hardware.

Wire format from the Arduino (one line per sample):

    <micros>,<a0>,<a1>,...,<d0>,<d1>,...\\n

Lines starting with '#' are treated as informational and ignored.
"""

from __future__ import annotations

import math
import queue
import random
import threading
import time
from dataclasses import dataclass, field

from . import config as cfg

try:
    import serial
    from serial.tools import list_ports
    HAVE_PYSERIAL = True
except ImportError:                                   # pragma: no cover
    serial = None
    list_ports = None
    HAVE_PYSERIAL = False


SIMULATOR_NAME = "Simulator (no hardware)"


@dataclass
class Sample:
    """One acquisition instant."""

    device_s: float                 # seconds since the sketch started streaming
    wall_s: float                   # host unix time when the line was parsed
    analog: tuple = field(default_factory=tuple)    # raw ADC counts
    digital: tuple = field(default_factory=tuple)   # 0 / 1


def available_ports() -> list[str]:
    """Serial ports plus the simulator entry, for the port dropdown."""
    ports = [SIMULATOR_NAME]
    if HAVE_PYSERIAL:
        try:
            ports += [p.device for p in list_ports.comports()]
        except Exception:
            pass
    return ports


# ---------------------------------------------------------------------------

class DataSource(threading.Thread):
    """Common behaviour: a background thread filling `self.queue`."""

    def __init__(self, sample_queue: queue.Queue):
        super().__init__(daemon=True)
        self.queue = sample_queue
        self._stop_event = threading.Event()
        self.error: str | None = None
        self.bad_lines = 0
        self.samples_read = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    def _emit(self, sample: Sample) -> None:
        self.samples_read += 1
        try:
            self.queue.put_nowait(sample)
        except queue.Full:
            pass          # GUI is behind; dropping the newest sample is safest


class SerialSource(DataSource):
    """Reads the Arduino's CSV stream."""

    def __init__(self, port: str, baud: int, sample_queue: queue.Queue):
        super().__init__(sample_queue)
        self.port = port
        self.baud = baud
        self._serial = None
        self._t0_us: int | None = None
        # Filled in from the sketch's "#ALCMAEON,..." reply to '?'.
        self.device_info: dict | None = None

    def run(self) -> None:
        if not HAVE_PYSERIAL:
            self.error = "pyserial is not installed (pip install pyserial)"
            return
        try:
            self._serial = serial.Serial(self.port, self.baud,
                                         timeout=cfg.SERIAL_TIMEOUT_S)
        except Exception as exc:
            self.error = f"Could not open {self.port}: {exc}"
            return

        try:
            time.sleep(2.0)                 # Arduino auto-reset on port open
            self._serial.reset_input_buffer()
            self._identify()                # ask the sketch what it is sending
            self._serial.write(b"S\n")      # 'S' = start streaming
            while not self.stopping:
                raw = self._serial.readline()
                if not raw:
                    continue
                self._parse(raw)
        except Exception as exc:            # unplugged cable, etc.
            if not self.stopping:
                self.error = f"Serial link lost: {exc}"
        finally:
            self._close()

    def _identify(self) -> None:
        """Ask the board to describe itself.

        The sketch answers '?' with  #ALCMAEON,<protocol>,<analog>,<digital>,<rate>
        which lets the app check the wiring matches its channel configuration
        instead of silently discarding every line. Sketches too old to answer
        simply leave device_info as None.
        """
        try:
            self._serial.write(b"?\n")
            deadline = time.time() + 2.0
            while time.time() < deadline and not self.stopping:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                if line.startswith("#ALCMAEON"):
                    self.device_info = self._read_info(line)
                    return
        except Exception:
            pass          # identification is optional; never block streaming

    @staticmethod
    def _read_info(line: str) -> dict | None:
        parts = line.lstrip("#").split(",")
        if len(parts) < 5:
            return None
        try:
            return {"protocol": int(parts[1]), "analog": int(parts[2]),
                    "digital": int(parts[3]), "sample_rate": float(parts[4])}
        except ValueError:
            return None

    def _parse(self, raw: bytes) -> None:
        line = raw.decode("ascii", errors="ignore").strip()
        if not line.startswith("#ALCMAEON") and line.startswith("#"):
            return
        if line.startswith("#ALCMAEON"):
            if self.device_info is None:
                self.device_info = self._read_info(line)
            return
        if not line:
            return
        parts = line.split(",")
        if len(parts) != 1 + cfg.N_ANALOG + cfg.N_DIGITAL:
            self.bad_lines += 1
            return
        try:
            micros = int(parts[0])
            analog = tuple(int(p) for p in parts[1:1 + cfg.N_ANALOG])
            digital = tuple(int(p) for p in parts[1 + cfg.N_ANALOG:])
        except ValueError:
            self.bad_lines += 1
            return

        if self._t0_us is None:
            self._t0_us = micros
        # micros() wraps every ~71 minutes; mask keeps the delta correct.
        delta = (micros - self._t0_us) & 0xFFFFFFFF
        self._emit(Sample(delta / 1e6, time.time(), analog, digital))

    def _close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.write(b"X\n")   # 'X' = stop streaming
                self._serial.flush()
                self._serial.close()
            except Exception:
                pass
            self._serial = None


class SimulatedSource(DataSource):
    """Synthetic signals so the app is usable without a board attached.

    EMG   : broadband noise gated by repeating contraction bursts.
    Pot 1 : slow sine sweep.  Pot 2 : slow triangle.
    Btn 1 : follows the contraction bursts.  Btn 2 : occasional taps.
    Extra channels beyond these fall back to gentle noise / no presses.
    """

    def __init__(self, sample_queue: queue.Queue, sample_rate: float):
        super().__init__(sample_queue)
        self.fs = sample_rate
        self.mains_hz = cfg.DEFAULT_NOTCH_HZ

    def run(self) -> None:
        dt = 1.0 / self.fs
        midscale = cfg.ADC_MAX_COUNTS / 2.0
        start = time.perf_counter()
        n = 0
        btn2_until = 0.0
        while not self.stopping:
            t = n * dt

            # --- burst envelope: 0.8 s contraction every 2.5 s ---------------
            phase = t % 2.5
            burst = 0.0
            if 0.6 < phase < 1.4:
                ramp = (phase - 0.6) / 0.8
                burst = math.sin(math.pi * ramp) ** 2

            emg = random.gauss(0.0, 1.0) * burst * 140.0        # muscle activity
            emg += random.gauss(0.0, 1.0) * 4.0                 # sensor noise
            emg += 12.0 * math.sin(2 * math.pi * self.mains_hz * t)   # mains hum
            emg += 6.0 * math.sin(2 * math.pi * 0.3 * t)        # baseline wander

            pot1 = midscale + midscale * 0.8 * math.sin(2 * math.pi * 0.08 * t)
            saw = (t * 0.05) % 1.0
            pot2 = cfg.ADC_MAX_COUNTS * (2 * saw if saw < 0.5 else 2 * (1 - saw))

            analog_pool = [midscale + emg, pot1, pot2]
            analog = tuple(
                int(max(0, min(cfg.ADC_MAX_COUNTS,
                               analog_pool[i] if i < len(analog_pool)
                               else midscale + random.gauss(0, 3))))
                for i in range(cfg.N_ANALOG)
            )

            if t > btn2_until and random.random() < 0.0006:
                btn2_until = t + 0.35
            digital_pool = [1 if burst > 0.25 else 0, 1 if t < btn2_until else 0]
            digital = tuple(digital_pool[i] if i < len(digital_pool) else 0
                            for i in range(cfg.N_DIGITAL))

            self._emit(Sample(t, time.time(), analog, digital))

            n += 1
            # Pace the loop to real time without drifting.
            sleep_for = (start + n * dt) - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)


def make_source(port: str, baud: int, sample_rate: float,
                sample_queue: queue.Queue) -> DataSource:
    """Factory used by the GUI: simulator or real serial port."""
    if port == SIMULATOR_NAME:
        return SimulatedSource(sample_queue, sample_rate)
    return SerialSource(port, baud, sample_queue)
