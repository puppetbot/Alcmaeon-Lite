# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Alcmaeon Lite.

Produces one self-contained executable that runs on a machine with no Python
and no libraries installed at all.

Built for you by:  "Build standalone app.bat" / "Build standalone app.command"
or by hand:        python -m PyInstaller packaging/alcmaeon.spec
"""

import sys
from pathlib import Path

APP_DIR = Path(SPECPATH).resolve().parent
ICON = APP_DIR / "packaging" / ("alcmaeon.ico" if sys.platform == "win32"
                                else "alcmaeon.png")

a = Analysis(
    [str(APP_DIR / "run_alcmaeon.py")],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "matplotlib.backends.backend_tkagg",
        "serial.tools.list_ports",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Trim the parts of matplotlib/numpy we never touch, so the binary stays
    # in the tens of megabytes rather than hundreds.
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "matplotlib.backends.backend_qt5agg",
        "matplotlib.backends.backend_webagg",
        "scipy", "pandas", "IPython", "jupyter", "notebook",
        "pytest", "sphinx", "PIL.ImageQt",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Alcmaeon Lite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                 # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,          # set True if you want file drops on macOS
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Alcmaeon Lite.app",
        icon=str(ICON) if ICON.exists() else None,
        bundle_identifier="net.alcmaeon.lite",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
        },
    )
