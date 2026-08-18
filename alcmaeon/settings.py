"""
Alcmaeon Lite -- saved settings
===============================

Keeps the channel layout the user set up in the app, so it survives restarts
without anyone editing config.py.

Written to `channels.json` beside the application. Delete that file and the
defaults in config.py take over again.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config as cfg

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "channels.json"


def describe_current() -> dict:
    """Capture the channel layout currently in force."""
    return {
        "analog": [
            {"name": c.name, "unit": c.unit, "zero_center": c.zero_center,
             "filter": c.default_filter, "view": c.default_view}
            for c in cfg.ANALOG_CHANNELS
        ],
        "digital": [
            {"name": c.name, "view": c.default_view}
            for c in cfg.DIGITAL_CHANNELS
        ],
    }


def save(layout: dict) -> bool:
    """Write the layout. Returns False if it could not be saved."""
    try:
        SETTINGS_PATH.write_text(json.dumps(layout, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False        # read-only folder: the app still works, it just forgets


def load() -> dict | None:
    """Read a previously saved layout, or None if there is not one."""
    try:
        if not SETTINGS_PATH.is_file():
            return None
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("analog"):
        return None
    return data


def clear() -> None:
    try:
        SETTINGS_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def apply_saved() -> bool:
    """Apply the saved layout at startup, if there is one."""
    layout = load()
    if layout is None:
        return False
    cfg.apply_layout_spec(layout["analog"], layout.get("digital", []))
    return True
