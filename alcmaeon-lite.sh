#!/bin/bash
# ===================================================================
#  Alcmaeon Lite -- Linux launcher
#  Make it executable once (chmod +x alcmaeon-lite.sh) or use the
#  bundled Alcmaeon Lite.desktop file, then double-click.
# ===================================================================
cd "$(dirname "$(readlink -f "$0")")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is not installed."
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-tk"
    echo "  Fedora:         sudo dnf install python3 python3-tkinter"
    read -r -p "Press enter to close." _
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "python3-tk is missing (Alcmaeon Lite needs it for its window)."
    echo "  Debian/Ubuntu:  sudo apt install python3-tk python3-venv"
    echo "  Fedora:         sudo dnf install python3-tkinter"
    read -r -p "Press enter to close." _
    exit 1
fi

exec python3 bootstrap.py "$@"
