#!/usr/bin/env sh
# Launch the N3 ROOT app on Linux/macOS.
# Note: the dji_blackbox root-shell exploit is Windows-only today. On Linux
# this app can still use an already-enabled ADB connection.
set -e
cd "$(dirname "$0")"
exec python3 app/main.py
