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
Alcmaeon Lite -- backdrop artwork
=================================

Uncoloured line art drawn behind the graphs: ruins, statuary, athletes.
Everything here is procedural -- no image files, no assets folder. Each piece
is a function returning a list of polylines, where a polyline is an (N, 2)
array of points in a 0..1 x 0..1 box (y up).

The renderer scales the box to the figure, keeps the aspect ratio, and strokes
everything in thin translucent white so it reads as a backdrop and never
competes with the traces.

To add your own piece: write a function returning polylines, then add it to
PIECES at the bottom. It joins the startup shuffle automatically.
"""

from __future__ import annotations

import math
import random

import numpy as np


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------

def line(*points) -> np.ndarray:
    """A polyline through the given (x, y) points."""
    return np.asarray(points, dtype=float)


def rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return line((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def arc(cx: float, cy: float, rx: float, ry: float,
        t0: float, t1: float, n: int = 48) -> np.ndarray:
    """Elliptical arc, angles in degrees."""
    t = np.radians(np.linspace(t0, t1, n))
    return np.column_stack((cx + rx * np.cos(t), cy + ry * np.sin(t)))


def ellipse(cx: float, cy: float, rx: float, ry: float, n: int = 64) -> np.ndarray:
    return arc(cx, cy, rx, ry, 0, 360, n)


def bezier(points, n: int = 40) -> np.ndarray:
    """Bezier of any degree through control `points` (de Casteljau)."""
    pts = np.asarray(points, dtype=float)
    t = np.linspace(0.0, 1.0, n)[:, None]
    while len(pts) > 1:
        pts = pts[:-1] * (1 - t[..., None]) + pts[1:] * t[..., None] \
            if pts.ndim == 2 else pts[:, :-1] * (1 - t[..., None]) + pts[:, 1:] * t[..., None]
        if pts.ndim == 3 and pts.shape[1] == 1:
            break
    return pts.reshape(-1, 2)


def curve(*segments, n: int = 36) -> np.ndarray:
    """Chain of bezier segments, each a tuple of control points."""
    out = []
    for seg in segments:
        piece = bezier(seg, n)
        out.append(piece if not out else piece[1:])
    return np.vstack(out)


def jagged(x0: float, x1: float, y: float, teeth: int = 5,
           depth: float = 0.02, seed: int = 0) -> np.ndarray:
    """A broken-stone top edge."""
    rng = random.Random(seed)
    xs = np.linspace(x0, x1, teeth * 2 + 1)
    ys = [y + (rng.uniform(-depth, depth) if i % 2 else rng.uniform(-depth / 2, depth / 2))
          for i in range(len(xs))]
    return np.column_stack((xs, ys))


def shift(polys, dx: float = 0.0, dy: float = 0.0, scale: float = 1.0,
          origin=(0.5, 0.0)):
    """Scale about `origin` then translate. Used to compose scenes."""
    ox, oy = origin
    out = []
    for p in polys:
        q = p.copy()
        q[:, 0] = ox + (q[:, 0] - ox) * scale + dx
        q[:, 1] = oy + (q[:, 1] - oy) * scale + dy
        out.append(q)
    return out


# ---------------------------------------------------------------------------
# Reusable architectural parts
# ---------------------------------------------------------------------------

def _column(x: float, base_y: float, top_y: float, width: float,
            flutes: int = 2, capital: bool = True, broken: bool = False,
            seed: int = 0) -> list[np.ndarray]:
    """One Doric column. Tapers slightly, like the real thing."""
    parts: list[np.ndarray] = []
    half_b = width / 2
    half_t = width / 2 * (0.92 if broken else 0.84)

    parts.append(line((x - half_b, base_y), (x - half_t, top_y)))
    parts.append(line((x + half_b, base_y), (x + half_t, top_y)))

    for i in range(flutes):
        f = (i + 1) / (flutes + 1)
        xb = x - half_b + 2 * half_b * f
        xt = x - half_t + 2 * half_t * f
        parts.append(line((xb, base_y + 0.01), (xt, top_y - 0.01)))

    if broken:
        parts.append(jagged(x - half_t, x + half_t, top_y, 3, width * 0.10, seed))
    else:
        parts.append(line((x - half_t, top_y), (x + half_t, top_y)))
        if capital:
            cap_h = width * 0.34
            parts.append(rect(x - half_b * 1.25, top_y, x + half_b * 1.25, top_y + cap_h))
    return parts


def _drum(x: float, y: float, w: float) -> list[np.ndarray]:
    """A fallen column drum lying on its side."""
    return [ellipse(x, y, w, w * 0.42, 40),
            arc(x, y, w * 0.62, w * 0.26, 0, 360, 32)]


def _steps(y: float, n: int = 3, width: float = 0.96,
           step_h: float = 0.018) -> list[np.ndarray]:
    parts = []
    for i in range(n):
        w = width - i * 0.045
        parts.append(rect(0.5 - w / 2, y + i * step_h, 0.5 + w / 2, y + (i + 1) * step_h))
    return parts


# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------

def parthenon() -> list[np.ndarray]:
    """The temple, weathered: a couple of columns down, the pediment broken."""
    parts: list[np.ndarray] = []
    ground, base = 0.06, 0.06
    parts += _steps(ground, 3, 0.98)
    base += 3 * 0.018

    top = 0.60
    n = 8
    xs = np.linspace(0.10, 0.90, n)
    broken = {2: 0.34, 6: 0.46}          # column index -> height it snapped at
    for i, x in enumerate(xs):
        parts += _column(x, base, broken.get(i, top), 0.058, flutes=2,
                         broken=(i in broken), seed=i * 7)

    cap_top = top + 0.058 * 0.34
    # architrave + triglyph frieze, missing over the broken columns
    break_x = 0.655
    for y0, y1 in ((cap_top, cap_top + 0.035), (cap_top + 0.035, cap_top + 0.075)):
        parts.append(line((0.06, y0), (break_x, y0)))
        parts.append(line((0.06, y1), (break_x, y1)))
        parts.append(line((0.06, y0), (0.06, y1)))
    # ragged vertical edge where the entablature sheared away
    edge = jagged(cap_top, cap_top + 0.075, break_x, 5, 0.014, 3)
    parts.append(np.column_stack((edge[:, 1], edge[:, 0])))

    frieze_y0, frieze_y1 = cap_top + 0.035, cap_top + 0.075
    for x in np.arange(0.10, 0.61, 0.075):
        parts.append(line((x, frieze_y0), (x, frieze_y1)))
        parts.append(line((x + 0.006, frieze_y0), (x + 0.006, frieze_y1)))

    # cornice and the surviving left half of the pediment
    corn = frieze_y1
    parts.append(line((0.04, corn), (0.66, corn), (0.66, corn + 0.02), (0.04, corn + 0.02),
                      (0.04, corn)))
    apex = (0.50, corn + 0.02 + 0.16)
    parts.append(line((0.04, corn + 0.02), apex))
    parts.append(line(apex, (0.695, corn + 0.077)))
    parts.append(line((0.695, corn + 0.077), (0.688, corn + 0.045),
                      (0.706, corn + 0.030), (0.690, corn + 0.020)))
    parts.append(line((0.08, corn + 0.035), (0.47, corn + 0.145)))

    parts += _drum(0.855, ground - 0.028, 0.045)
    parts += _drum(0.945, ground - 0.032, 0.034)
    parts.append(line((0.0, ground), (1.0, ground)))
    return parts


def colonnade() -> list[np.ndarray]:
    """A ruined stoa: broken columns, scattered drums, a fragment of architrave."""
    parts: list[np.ndarray] = []
    ground = 0.10
    heights = [0.78, 0.44, 0.80, 0.62, 0.30, 0.76, 0.52]
    xs = np.linspace(0.10, 0.90, len(heights))
    for i, (x, h) in enumerate(zip(xs, heights)):
        parts += _column(x, ground, h, 0.075, flutes=3, broken=(h < 0.70), seed=i)

    # surviving architrave spanning the two tallest on the left
    parts.append(rect(xs[0] - 0.06, 0.80, xs[2] + 0.06, 0.855))
    parts.append(line((xs[0] - 0.06, 0.828), (xs[2] + 0.06, 0.828)))

    parts += _drum(0.30, ground + 0.035, 0.055)
    parts += _drum(0.62, ground + 0.03, 0.045)
    parts += _drum(0.70, ground + 0.028, 0.04)
    parts.append(line((0.0, ground), (1.0, ground)))
    parts.append(line((0.0, ground - 0.02), (0.42, ground - 0.02)))
    return parts


def amphora() -> list[np.ndarray]:
    """A black-figure amphora with a meander band."""
    parts: list[np.ndarray] = []
    cx = 0.5

    right = curve(
        ((cx + 0.075, 0.90), (cx + 0.105, 0.87), (cx + 0.10, 0.83)),   # lip
        ((cx + 0.095, 0.79), (cx + 0.055, 0.76), (cx + 0.052, 0.72)),  # neck
        ((cx + 0.050, 0.66), (cx + 0.215, 0.60), (cx + 0.215, 0.44)),  # shoulder
        ((cx + 0.215, 0.30), (cx + 0.120, 0.20), (cx + 0.075, 0.14)),  # belly to foot
        ((cx + 0.060, 0.12), (cx + 0.090, 0.10), (cx + 0.090, 0.075)),
        ((cx + 0.090, 0.06), (cx + 0.085, 0.055), (cx + 0.075, 0.05)),
    )
    left = right.copy()
    left[:, 0] = 2 * cx - left[:, 0]
    parts += [right, left]
    parts.append(line((cx - 0.075, 0.90), (cx + 0.075, 0.90)))
    parts.append(line((cx - 0.075, 0.05), (cx + 0.075, 0.05)))
    parts.append(line((cx - 0.098, 0.845), (cx + 0.098, 0.845)))

    for sign in (1, -1):
        for out, drop in ((0.185, 0.150), (0.152, 0.128)):     # outer + inner edge
            parts.append(curve(
                ((cx + sign * 0.053, 0.762), (cx + sign * out, 0.775),
                 (cx + sign * out, 0.700)),
                ((cx + sign * out, 0.640), (cx + sign * drop, 0.612),
                 (cx + sign * drop, 0.585)),
            ))

    for y in (0.540, 0.512, 0.335, 0.305):
        w = 0.212 if y > 0.5 else 0.190
        parts.append(line((cx - w, y), (cx + w, y)))

    # meander band around the belly
    y0, y1 = 0.305, 0.335
    x = cx - 0.18
    while x < cx + 0.15:
        u = 0.030
        parts.append(line((x, y0), (x, y1), (x + u * 0.8, y1), (x + u * 0.8, y0 + u * 0.25),
                          (x + u * 0.25, y0 + u * 0.25), (x + u * 0.25, y0 + u * 0.6)))
        x += u
    return parts


def bust() -> list[np.ndarray]:
    """A marble head in profile on a plinth, chipped at the nose."""
    parts: list[np.ndarray] = []

    # face profile, facing left: brow, nose, lips, chin
    face = curve(
        ((0.520, 0.880), (0.430, 0.878), (0.404, 0.828)),   # forehead
        ((0.392, 0.800), (0.386, 0.790), (0.398, 0.772)),   # brow ridge
        ((0.372, 0.742), (0.352, 0.716), (0.382, 0.706)),   # nose
        ((0.402, 0.700), (0.404, 0.700), (0.408, 0.686)),   # nostril
        ((0.414, 0.672), (0.386, 0.668), (0.402, 0.652)),   # upper lip
        ((0.418, 0.640), (0.392, 0.630), (0.406, 0.616)),   # lower lip
        ((0.418, 0.604), (0.436, 0.600), (0.440, 0.578)),   # chin
        ((0.444, 0.556), (0.470, 0.548), (0.508, 0.552)),   # jaw
    )
    parts.append(face)

    # skull and hair mass
    parts.append(curve(
        ((0.520, 0.880), (0.610, 0.878), (0.646, 0.812)),
        ((0.678, 0.748), (0.660, 0.640), (0.596, 0.586)),
    ))
    parts.append(curve(
        ((0.470, 0.862), (0.540, 0.900), (0.612, 0.856)),
        ((0.652, 0.830), (0.646, 0.792), (0.628, 0.772)),
    ))
    for cx, cy, r in ((0.612, 0.800, 0.024), (0.640, 0.752, 0.021),
                      (0.624, 0.702, 0.019), (0.598, 0.652, 0.017)):
        parts.append(arc(cx, cy, r, r, 200, 520, 30))

    parts.append(arc(0.470, 0.760, 0.030, 0.016, 200, 340, 24))       # eye
    parts.append(line((0.452, 0.792), (0.492, 0.798)))                 # brow
    parts.append(arc(0.556, 0.716, 0.026, 0.034, 250, 80, 26))         # ear

    # neck into the shoulders of the herm
    parts.append(curve(((0.508, 0.552), (0.500, 0.520), (0.494, 0.478)),
                       ((0.490, 0.452), (0.446, 0.440), (0.404, 0.428))))
    parts.append(curve(((0.596, 0.586), (0.594, 0.520), (0.598, 0.470)),
                       ((0.604, 0.446), (0.652, 0.438), (0.694, 0.426))))
    parts.append(jagged(0.404, 0.694, 0.428, 6, 0.016, 11))

    # plinth
    parts.append(rect(0.372, 0.300, 0.726, 0.418))
    parts.append(rect(0.340, 0.250, 0.758, 0.300))
    parts.append(rect(0.316, 0.210, 0.782, 0.250))
    parts.append(line((0.372, 0.392), (0.726, 0.392)))
    return parts


def discus_thrower() -> list[np.ndarray]:
    """An athlete mid-throw, drawn the way a vase painter would: outlines only."""
    parts: list[np.ndarray] = []

    parts.append(ellipse(0.585, 0.760, 0.042, 0.050, 48))              # head
    parts.append(arc(0.585, 0.772, 0.048, 0.052, 20, 200, 30))         # hair
    parts.append(line((0.578, 0.710), (0.560, 0.688)))                 # neck

    # torso: coiled forward over the front leg
    parts.append(curve(
        ((0.552, 0.690), (0.486, 0.656), (0.462, 0.598)),
        ((0.442, 0.556), (0.438, 0.518), (0.452, 0.486)),
    ))
    parts.append(curve(
        ((0.610, 0.700), (0.596, 0.640), (0.556, 0.584)),
        ((0.526, 0.542), (0.510, 0.514), (0.508, 0.482)),
    ))
    parts.append(line((0.452, 0.486), (0.508, 0.482)))                 # hips
    parts.append(arc(0.520, 0.620, 0.036, 0.044, 120, 260, 24))        # ribs

    # throwing arm sweeping back and up, discus in hand
    parts.append(curve(
        ((0.604, 0.686), (0.686, 0.700), (0.742, 0.760)),
        ((0.786, 0.808), (0.812, 0.856), (0.826, 0.888)),
    ))
    parts.append(curve(
        ((0.630, 0.660), (0.706, 0.676), (0.760, 0.736)),
        ((0.800, 0.780), (0.828, 0.834), (0.846, 0.874)),
    ))
    parts.append(ellipse(0.850, 0.902, 0.060, 0.030, 40))              # discus
    parts.append(arc(0.850, 0.902, 0.030, 0.015, 0, 360, 24))

    # leading arm reaching down across the body
    parts.append(curve(
        ((0.552, 0.678), (0.454, 0.640), (0.396, 0.572)),
        ((0.358, 0.528), (0.336, 0.492), (0.328, 0.466)),
    ))
    parts.append(curve(
        ((0.566, 0.646), (0.486, 0.610), (0.430, 0.550)),
        ((0.394, 0.510), (0.366, 0.478), (0.354, 0.454)),
    ))
    parts.append(line((0.328, 0.466), (0.316, 0.442), (0.336, 0.432), (0.358, 0.446),
                      (0.354, 0.454)))

    # braced front leg
    parts.append(curve(((0.452, 0.486), (0.408, 0.430), (0.372, 0.352)),
                       ((0.348, 0.300), (0.318, 0.248), (0.286, 0.208))))
    parts.append(curve(((0.508, 0.482), (0.470, 0.418), (0.436, 0.344)),
                       ((0.410, 0.288), (0.378, 0.236), (0.344, 0.202))))
    parts.append(line((0.286, 0.208), (0.252, 0.194), (0.264, 0.176), (0.346, 0.182),
                      (0.344, 0.202)))

    # trailing leg, toe down
    parts.append(curve(((0.504, 0.492), (0.578, 0.446), (0.640, 0.376)),
                       ((0.688, 0.322), (0.724, 0.262), (0.742, 0.208))))
    parts.append(curve(((0.470, 0.470), (0.548, 0.416), (0.610, 0.348)),
                       ((0.656, 0.296), (0.690, 0.240), (0.706, 0.196))))
    parts.append(line((0.742, 0.208), (0.766, 0.190), (0.752, 0.174), (0.700, 0.182),
                      (0.706, 0.196)))

    parts.append(line((0.06, 0.176), (0.94, 0.176)))                   # ground
    return parts


def temple_ruin() -> list[np.ndarray]:
    """A distant hillside ruin: a few standing columns and a fallen entablature."""
    parts: list[np.ndarray] = []
    ground = 0.22
    parts.append(curve(((0.0, 0.30), (0.16, 0.20), (0.34, ground)),
                       ((0.56, 0.24), (0.78, 0.19), (1.0, 0.26))))

    for i, (x, h) in enumerate(((0.26, 0.74), (0.36, 0.70), (0.46, 0.76), (0.56, 0.48))):
        parts += _column(x, ground + 0.01, h, 0.05, flutes=2,
                         capital=(h > 0.6), seed=i * 5)
        if h < 0.6:
            parts.append(jagged(x - 0.022, x + 0.022, h, 3, 0.014, i))

    parts.append(rect(0.215, 0.775, 0.505, 0.815))
    parts.append(jagged(0.505, 0.585, 0.795, 3, 0.014, 9))

    # a fallen section lying in the grass
    parts.append(rect(0.640, ground + 0.005, 0.860, ground + 0.045))
    parts.append(line((0.640, ground + 0.028), (0.860, ground + 0.028)))
    parts += _drum(0.900, ground + 0.028, 0.040)
    parts += _drum(0.610, ground + 0.022, 0.030)

    # cypress trees, because it is always cypresses
    for x, h in ((0.10, 0.30), (0.145, 0.24), (0.92, 0.26)):
        parts.append(curve(((x, ground + 0.02), (x - 0.032, ground + h * 0.6),
                            (x, ground + h)),
                           ((x + 0.032, ground + h * 0.6), (x, ground + 0.02),
                            (x, ground + 0.02))))
    return parts


PIECES = {
    "parthenon": parthenon,
    "colonnade": colonnade,
    "amphora": amphora,
    "bust": bust,
    "discus": discus_thrower,
    "ruin": temple_ruin,
}


def get(name: str | None = None) -> tuple[str, list[np.ndarray]]:
    """Return (name, polylines). With no name, pick one at random."""
    if not name or name == "random":
        name = random.choice(list(PIECES))
    if name not in PIECES:
        name = "parthenon"
    return name, PIECES[name]()
