#!/bin/bash
# MeshDEX installer for Raspberry Pi
# Tested on Pi Zero 2 W, Raspberry Pi OS (Debian Trixie/Bookworm)

set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$(whoami)}"
USER_HOME=$(eval echo "~$USER_NAME")

echo "=== MeshDEX Installer ==="
echo "Install dir: $INSTALL_DIR"
echo "User: $USER_NAME"
echo ""

# ─── 1. SYSTEM PACKAGES ──────────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
sudo apt update -qq
sudo apt install -y \
    python3-pygame \
    python3-psutil \
    fonts-dejavu \
    2>/dev/null
echo "  ✓ pygame, psutil, fonts-dejavu installed"

# ─── 2. PYTHON PACKAGES ──────────────────────────────────────────────────────
echo "[2/5] Installing Python packages..."
pip3 install pyte --break-system-packages -q
echo "  ✓ pyte installed (terminal emulator backend)"

# ─── 3. MAKE SCRIPTS EXECUTABLE ──────────────────────────────────────────────
echo "[3/5] Setting permissions..."
chmod +x "$INSTALL_DIR/meshdex.py"
chmod +x "$INSTALL_DIR/launch.sh"
echo "  ✓ Scripts are executable"

# ─── 4. SWAP FILE ────────────────────────────────────────────────────────────
echo "[4/5] Checking swap..."
if [ ! -f /swapfile ]; then
    echo "  Creating 2GB swapfile (recommended for Pi Zero 2 W)..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    fi
    echo "  ✓ 2GB swapfile created"
else
    echo "  ✓ Swapfile already exists"
fi

# ─── 5. BASH SETTINGS ────────────────────────────────────────────────────────
echo "[5/5] Configuring bash..."
BASHRC="$USER_HOME/.bashrc"
if ! grep -q 'enable-bracketed-paste' "$BASHRC" 2>/dev/null; then
    echo 'bind "set enable-bracketed-paste off"' >> "$BASHRC"
    echo "  ✓ Disabled bracketed paste (prevents ?2004h artifacts)"
else
    echo "  ✓ Bracketed paste already disabled"
fi

# ─── 6. KIOSK SETUP (OPTIONAL) ───────────────────────────────────────────────
echo ""
echo "[Optional] Kiosk autostart setup..."
read -p "  Configure MeshDEX to launch automatically on boot? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    LABWC_DIR="$USER_HOME/.config/labwc"
    mkdir -p "$LABWC_DIR"

    if [ ! -f "$LABWC_DIR/autostart" ]; then
        cat > "$LABWC_DIR/autostart" << 'EOF'
/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &
/usr/bin/kanshi &
/usr/bin/lxsession-xdg-autostart
EOF
        echo "  ✓ Created labwc autostart (taskbar disabled)"
    fi

    if ! grep -q "meshdex\|MeshDEX" "$LABWC_DIR/autostart" 2>/dev/null; then
        echo "" >> "$LABWC_DIR/autostart"
        echo "# MeshDEX" >> "$LABWC_DIR/autostart"
        echo "sleep 2 && $INSTALL_DIR/launch.sh &" >> "$LABWC_DIR/autostart"
        echo "  ✓ MeshDEX added to labwc autostart"
    else
        echo "  ✓ MeshDEX already in autostart"
    fi
else
    echo "  Skipped — launch manually with: $INSTALL_DIR/launch.sh"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "To launch MeshDEX:"
echo "  $INSTALL_DIR/launch.sh"
echo ""
echo "If MeshTTY is installed at ~/MeshTTY, it will auto-launch in the terminal."
echo "Install MeshTTY: https://github.com/kendelmccarley/MeshTTY"
echo ""
