#!/bin/bash
# MeshDEX launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure swap is active
sudo swapon /swapfile 2>/dev/null || true

# Kill any previous instance
pkill -f "meshdex.py" 2>/dev/null || true
sleep 0.5

# Disable taskbar if running (kiosk mode)
pkill -f "wf-panel-pi" 2>/dev/null || true

# Set display
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

while true; do
    python3 "$SCRIPT_DIR/meshdex.py" "$@"
    EXIT=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S')  meshdex.py exited (code $EXIT), restarting in 3s..." >> ~/meshdex.log
    sleep 3
done
