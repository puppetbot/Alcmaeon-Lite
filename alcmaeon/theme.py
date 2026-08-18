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
Alcmaeon Lite -- theme
======================

Dark, minimal, terminal-ish. Incognito greys, one blue, white line art.

Contains:
  * PALETTE / FONTS  -- change these and the whole app follows
  * apply_theme()    -- ttk styling for the dark scheme
  * RoundedPanel     -- a rounded card you can pack widgets into
  * RoundedButton    -- a rounded, hover-aware button (ttk can't round corners)
  * style_axes()     -- matplotlib axes with rounded translucent panels
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from matplotlib.patches import FancyBboxPatch


PALETTE = {
    # greys -- incognito
    "bg":         "#1f2023",   # window
    "surface":    "#2a2b2f",   # cards
    "surface_hi": "#34363b",   # hover / inputs
    "line":       "#3d4045",   # hairlines
    # ink
    "text":       "#e3e5e8",
    "muted":      "#8a9098",
    "faint":      "#5f656d",
    # blue
    "blue":       "#6E9BC5",   # primary accent
    "blue_soft":  "#9DBEDC",
    "blue_deep":  "#22364F",   # filled buttons
    "art":        "#FFFFFF",   # line art -- always white, never a trace colour
    "warn":       "#c87a68",
}

# Traces sit in the blue family so the white art stays clearly "not data".
TRACE_COLORS = [
    "#7FB2E5",   # primary blue
    "#79C0A8",   # verdigris
    "#B58BC4",   # amethyst
    "#6FD3D6",   # cyan
    "#D6A0B5",   # rose
    "#8E9BB3",   # slate
]

# Filled in by apply_theme() once a Tk root exists.
FONTS: dict[str, tuple] = {
    "title": ("TkDefaultFont", 16),
    "ui": ("TkDefaultFont", 9),
    "small": ("TkDefaultFont", 8),
    "label": ("TkDefaultFont", 9, "bold"),
}

_MONO_CANDIDATES = ["JetBrains Mono", "Cascadia Mono", "SF Mono", "Menlo",
                    "Consolas", "DejaVu Sans Mono", "Liberation Mono",
                    "Ubuntu Mono", "Courier New"]


def trace_color(index: int) -> str:
    return TRACE_COLORS[index % len(TRACE_COLORS)]


def _pick_mono() -> str:
    available = set(tkfont.families())
    for name in _MONO_CANDIDATES:
        if name in available:
            return name
    return "TkFixedFont"


def apply_theme(root: tk.Misc) -> ttk.Style:
    mono = _pick_mono()
    FONTS.update({
        "title": (mono, 17),
        "ui": (mono, 9),
        "small": (mono, 8),
        "label": (mono, 9, "bold"),
        "tiny": (mono, 7),
    })

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    surface, text = PALETTE["surface"], PALETTE["text"]

    # Defaults assume "inside a card", which is where most widgets live.
    style.configure(".", background=surface, foreground=text, font=FONTS["ui"],
                    borderwidth=0, focuscolor=PALETTE["blue"])
    style.configure("TFrame", background=surface)
    style.configure("Page.TFrame", background=PALETTE["bg"])

    style.configure("TLabel", background=surface, foreground=text)
    style.configure("Page.TLabel", background=PALETTE["bg"], foreground=text)
    style.configure("Muted.TLabel", background=surface, foreground=PALETTE["muted"],
                    font=FONTS["small"])
    style.configure("Faint.TLabel", background=surface, foreground=PALETTE["faint"],
                    font=FONTS["tiny"])
    style.configure("Head.TLabel", background=surface, foreground=PALETTE["blue"],
                    font=FONTS["label"])

    style.configure("TCheckbutton", background=surface, foreground=text,
                    indicatorcolor=PALETTE["surface_hi"], font=FONTS["ui"])
    style.map("TCheckbutton",
              background=[("active", surface)],
              indicatorcolor=[("selected", PALETTE["blue"])],
              foreground=[("active", PALETTE["blue_soft"])])

    style.configure("TEntry", fieldbackground=PALETTE["surface_hi"], foreground=text,
                    insertcolor=PALETTE["blue"], bordercolor=PALETTE["line"],
                    lightcolor=PALETTE["line"], darkcolor=PALETTE["line"],
                    borderwidth=1, padding=3)
    style.map("TEntry", bordercolor=[("focus", PALETTE["blue"])])

    style.configure("TCombobox", fieldbackground=PALETTE["surface_hi"],
                    background=PALETTE["surface_hi"], foreground=text,
                    arrowcolor=PALETTE["blue"], bordercolor=PALETTE["line"],
                    lightcolor=PALETTE["line"], darkcolor=PALETTE["line"],
                    selectbackground=PALETTE["surface_hi"],
                    selectforeground=text, borderwidth=1, padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", PALETTE["surface_hi"])],
              bordercolor=[("focus", PALETTE["blue"]), ("hover", PALETTE["blue_deep"])])

    # clam draws 3D edges on scrollbars; matching them to the fill keeps it flat
    style.configure("TScrollbar", background=PALETTE["line"],
                    troughcolor=PALETTE["bg"], bordercolor=PALETTE["bg"],
                    lightcolor=PALETTE["line"], darkcolor=PALETTE["line"],
                    arrowcolor=PALETTE["faint"], borderwidth=0, relief="flat",
                    width=9)
    style.map("TScrollbar",
              background=[("active", PALETTE["faint"])],
              lightcolor=[("active", PALETTE["faint"])],
              darkcolor=[("active", PALETTE["faint"])])
    style.configure("TSeparator", background=PALETTE["line"])

    style.configure("TScale", background=PALETTE["surface"],
                    troughcolor=PALETTE["surface_hi"], bordercolor=PALETTE["line"],
                    lightcolor=PALETTE["blue"], darkcolor=PALETTE["blue"])
    style.map("TScale", background=[("active", PALETTE["surface"])])

    root.option_add("*TCombobox*Listbox.background", PALETTE["surface_hi"])
    root.option_add("*TCombobox*Listbox.foreground", text)
    root.option_add("*TCombobox*Listbox.selectBackground", PALETTE["blue_deep"])
    root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text"])
    root.option_add("*TCombobox*Listbox.font", FONTS["ui"])
    return style


# ---------------------------------------------------------------------------
# Rounded widgets (tk has no corner radius, so these are drawn on canvases)
# ---------------------------------------------------------------------------

def round_rect_points(x0, y0, x1, y1, r, steps: int = 6):
    """Polygon points tracing a rounded rectangle."""
    r = max(0, min(r, abs(x1 - x0) / 2, abs(y1 - y0) / 2))
    pts: list[float] = []
    corners = (
        (x1 - r, y1 - r, 0, 90),      # bottom-right in canvas coords
        (x0 + r, y1 - r, 90, 180),
        (x0 + r, y0 + r, 180, 270),
        (x1 - r, y0 + r, 270, 360),
    )
    import math
    for cx, cy, a0, a1 in corners:
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class RoundedPanel(tk.Frame):
    """A rounded card. Pack children into `.body`."""

    def __init__(self, master, title: str | None = None, radius: int = 12,
                 pad: int = 12, fill: str | None = None,
                 outline: str | None = None, page_bg: str | None = None, **kw):
        page_bg = page_bg or PALETTE["bg"]
        super().__init__(master, bg=page_bg, **kw)
        self.fill = fill or PALETTE["surface"]
        self.outline = outline or PALETTE["line"]
        self.radius = radius
        self.pad = pad

        self.canvas = tk.Canvas(self, bg=page_bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=self.fill)
        if title:
            head = tk.Frame(self.body, bg=self.fill)
            head.pack(fill="x", pady=(0, 6))
            tk.Label(head, text=title, bg=self.fill, fg=PALETTE["blue"],
                     font=FONTS["label"]).pack(side="left")
            tk.Frame(head, bg=PALETTE["line"], height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0), pady=(7, 0))

        self._win = self.canvas.create_window(pad, pad, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._fit)
        self.canvas.bind("<Configure>", self._fit)

    def _fit(self, _event=None) -> None:
        width = self.canvas.winfo_width()
        height = self.body.winfo_reqheight() + 2 * self.pad
        if height != self.canvas.winfo_height():
            self.canvas.configure(height=height)
        self.canvas.itemconfigure(self._win, width=max(1, width - 2 * self.pad))
        self.canvas.delete("panel")
        self.canvas.create_polygon(
            round_rect_points(1, 1, max(2, width - 1), max(2, height - 1), self.radius),
            fill=self.fill, outline=self.outline, width=1, smooth=False, tags="panel")
        self.canvas.tag_lower("panel")


class Toggle(tk.Label):
    """A `[x] label` checkbox. ttk's indicator can't be themed dark reliably,
    and brackets suit the terminal look better anyway."""

    def __init__(self, master, text: str, variable: tk.BooleanVar,
                 bg: str | None = None, font_key: str = "ui"):
        self.var = variable
        self.label_text = text
        super().__init__(master, bg=bg or PALETTE["surface"], anchor="w",
                         font=FONTS[font_key], cursor="hand2", bd=0,
                         padx=0, pady=1)
        self.bind("<Button-1>", lambda e: self.var.set(not bool(self.var.get())))
        self.bind("<Enter>", lambda e: self.configure(fg=PALETTE["blue_soft"]))
        self.bind("<Leave>", lambda e: self._render())
        self.var.trace_add("write", lambda *_: self._render())
        self._render()

    def _render(self, *_args) -> None:
        on = bool(self.var.get())
        self.configure(text=f"[{'x' if on else ' '}] {self.label_text}",
                       fg=PALETTE["text"] if on else PALETTE["faint"])


class RoundedButton(tk.Canvas):
    """Flat rounded button with hover feedback."""

    def __init__(self, master, text: str, command=None, kind: str = "normal",
                 radius: int = 9, height: int = 28, page_bg: str | None = None):
        page_bg = page_bg or PALETTE["surface"]
        super().__init__(master, bg=page_bg, highlightthickness=0, bd=0,
                         height=height, width=48)
        self.command = command
        self.radius = radius
        self.kind = kind
        self._text = text
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # colours per kind: (fill, hover fill, text, outline)
    def _colors(self):
        if self.kind == "primary":
            return (PALETTE["blue_deep"], "#2c4666", PALETTE["blue_soft"], PALETTE["blue"])
        if self.kind == "danger":
            return (PALETTE["surface_hi"], "#4a3430", PALETTE["warn"], PALETTE["warn"])
        return (PALETTE["surface_hi"], PALETTE["line"], PALETTE["text"], PALETTE["line"])

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        fill, hover, fg, outline = self._colors()
        self.create_polygon(round_rect_points(1, 1, w - 1, h - 1, self.radius),
                            fill=hover if self._hover else fill,
                            outline=outline if self._hover else PALETTE["line"],
                            width=1, smooth=False)
        self.create_text(w / 2, h / 2 + 1, text=self._text, fill=fg, font=FONTS["ui"])

    def _on_enter(self, _e):
        self._hover = True
        self.configure(cursor="hand2")
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _on_click(self, _e):
        if self.command:
            self.command()


# ---------------------------------------------------------------------------
# matplotlib
# ---------------------------------------------------------------------------

def _rgba(hex_color: str, alpha: float) -> tuple:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (r, g, b, alpha)


def style_axes(ax, translucent: bool = True, rounded: bool = True) -> None:
    """Minimal dark axes on a rounded, optionally see-through panel."""
    alpha = 0.28 if translucent else 1.0
    face = _rgba(PALETTE["surface"], alpha)

    ax.set_facecolor("none")
    ax.patch.set_visible(False)
    if rounded:
        panel = FancyBboxPatch(
            (0, 0), 1, 1, transform=ax.transAxes,
            boxstyle="round,pad=0,rounding_size=0.025",
            mutation_aspect=0.30, facecolor=face,
            edgecolor=_rgba(PALETTE["line"], 0.9), linewidth=1.0,
            zorder=-2, clip_on=False, in_layout=False)
        ax.add_patch(panel)
    else:
        ax.patch.set_visible(True)
        ax.set_facecolor(face)

    ax.grid(True, color=_rgba(PALETTE["line"], 0.40), linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(colors=PALETTE["faint"], labelsize=7.5, length=0, pad=4)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for axis in (ax.xaxis, ax.yaxis):
        axis.label.set_color(PALETTE["muted"])
        axis.label.set_size(8)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily("monospace")


def legend_kwargs() -> dict:
    return dict(loc="upper right", fontsize=7, framealpha=0.0,
                labelcolor=PALETTE["muted"], handlelength=1.6,
                borderpad=0.3, labelspacing=0.25)
