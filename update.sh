#!/bin/bash
# MeshDEX updater — pulls latest code from GitHub

set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== MeshDEX Updater ==="
echo "Install dir: $INSTALL_DIR"
echo ""

cd "$INSTALL_DIR"

# Check for uncommitted local changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "WARNING: You have local changes that will be overwritten."
    read -p "Continue? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
    git stash
fi

echo "[1/2] Pulling latest changes from GitHub..."
git pull origin main
echo "  ✓ Up to date"

echo "[2/2] Setting permissions..."
chmod +x "$INSTALL_DIR/meshdex.py"
chmod +x "$INSTALL_DIR/launch.sh"
echo "  ✓ Done"

echo ""
echo "=== Update complete ==="
echo ""
echo "Restart MeshDEX to apply changes:"
echo "  $INSTALL_DIR/launch.sh"
echo ""
