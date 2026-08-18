#!/usr/bin/env python3
"""Render the app icon from the line art. Run it if you change the drawing:
       python packaging/make_icon.py
Writes packaging/alcmaeon.png and packaging/alcmaeon.ico."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from alcmaeon import artwork
from alcmaeon.theme import PALETTE

SIZE = 1024
fig = plt.figure(figsize=(SIZE / 100, SIZE / 100), dpi=100, facecolor=PALETTE["bg"])
ax = fig.add_axes([0, 0, 1, 1])
ax.set_facecolor(PALETTE["bg"])
for poly in artwork.parthenon():
    ax.plot(poly[:, 0], poly[:, 1], color=PALETTE["art"], lw=3.2,
            solid_joinstyle="round", solid_capstyle="round")
ax.set_xlim(-0.02, 1.02)
ax.set_ylim(-0.16, 1.18)
ax.set_aspect("equal", adjustable="datalim")
ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values():
    s.set_visible(False)

png = HERE / "alcmaeon.png"
fig.savefig(png, dpi=100, facecolor=PALETTE["bg"])
print("wrote", png)

try:
    from PIL import Image
    image = Image.open(png).convert("RGBA")
    ico = HERE / "alcmaeon.ico"
    image.save(ico, sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    print("wrote", ico)
except ImportError:
    print("pillow not installed - skipped the .ico (windows icon)")
