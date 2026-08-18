#!/bin/bash
# Builds a standalone Alcmaeon Lite.app that runs with no Python installed.
cd "$(dirname "$0")" || exit 1
python3 bootstrap.py --build
read -r -p "Press return to close." _
