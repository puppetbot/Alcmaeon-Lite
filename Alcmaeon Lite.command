#!/bin/bash
# ===================================================================
#  Alcmaeon Lite -- macOS launcher
#  Double-click this file. If macOS blocks it, right-click it once
#  and choose Open. First run installs what it needs.
# ===================================================================
cd "$(dirname "$0")" || exit 1

# --------------------------------------------------------------------
# Finding a REAL python 3.
#
# macOS ships /usr/bin/python3 as a stub. Running it when Apple's
# Command Line Tools are absent pops up "requires the command line
# developer tools", and that installer frequently fails with
# "not available on the Software Update server". So we look for a
# genuine install first and only fall back to /usr/bin/python3 when
# the developer tools are actually present.
# --------------------------------------------------------------------
PY=""

# python.org installs (preferred: they include Tcl/Tk for the window)
for v in 3.15 3.14 3.13 3.12 3.11 3.10 3.9; do
    candidate="/Library/Frameworks/Python.framework/Versions/$v/bin/python3"
    if [ -x "$candidate" ]; then PY="$candidate"; break; fi
done

# Homebrew installs
if [ -z "$PY" ]; then
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [ -x "$candidate" ]; then PY="$candidate"; break; fi
    done
fi

# Apple's python3, but only if the developer tools are really installed
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ]; then
    if /usr/bin/python3 -c "import sys" >/dev/null 2>&1; then
        PY="/usr/bin/python3"
    fi
fi

if [ -n "$PY" ]; then
    exec "$PY" bootstrap.py "$@"
fi

# --------------------------------------------------------------------
# Nothing usable found -- offer to open the download page.
# --------------------------------------------------------------------
MESSAGE="Python 3 is not installed on this Mac.

The python3 that comes with macOS is only a placeholder. If you saw \"unavailable on the Software Update server\", that is Apple's installer failing -- it is not a problem with Alcmaeon Lite.

Download the official installer from python.org instead (about 60 MB), run it, then open Alcmaeon Lite again."

CHOICE=$(osascript -e "display dialog \"$MESSAGE\" buttons {\"Cancel\", \"Open python.org\"} default button \"Open python.org\" with title \"Alcmaeon Lite\" with icon caution" 2>/dev/null)

case "$CHOICE" in
    *"Open python.org"*) open "https://www.python.org/downloads/macos/" ;;
    *) echo "Install Python 3 from https://www.python.org/downloads/macos/" ;;
esac
