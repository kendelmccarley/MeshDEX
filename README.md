# MeshDEX

> **PRE-RELEASE — v0.1.0 beta.**  
> Core functionality is working. Tested on Raspberry Pi Zero 2 W with a 1366×768 HDMI display.

MeshDEX is a lightweight, fullscreen terminal UI framework for the Raspberry Pi Zero 2 W, designed as a display layer for [MeshTTY](https://github.com/kendelmccarley/MeshTTY) — a terminal TUI client for [Meshtastic](https://meshtastic.org/) LoRa mesh radio networks.

Inspired by [eDEX-UI](https://github.com/GitSquared/edex-ui), MeshDEX delivers the same sci-fi terminal aesthetic at a fraction of the resource cost. Instead of Electron + Node.js (~400MB RAM), it runs on **pure Python + pygame/SDL2** (~30MB RAM).

---

## Screenshot

![MeshDEX running MeshTTY](assets/screenshot.jpg)

*(Add your own screenshot here)*

---

## Layout

```
┌──────────────┬─────────────────────────────────────────┬──────────────┐
│ PANEL SYSTEM │ TERMINAL          MAIN SHELL  EMPTY ...  │ PANEL NETWRK │
│              │                                          │              │
│  19:43:31    │                                          │ NETWORK      │
│              │                                          │ STATUS       │
│  CPU graphs  │         80×24 PTY terminal               │              │
│  Memory dots │         (MeshTTY runs here)              │  Globe       │
│  Processes   │                                          │              │
│              │                                          │  Net traffic │
├──────────────┴──────────────────────────────────┐       │              │
│ FILESYSTEM              /home/digits            │       │              │
│ [folder] [folder] [folder] [file] ...           │       │              │
└─────────────────────────────────────────────────┘       └──────────────┘
                    [ K E Y B O A R D   V I S U A L I Z E R          ]
```

**Left panel:** Large clock, date/uptime, system info grid, dual CPU waveforms, temperature/frequency/task count, memory dot grid, swap bar, top processes list

**Center:** Full 80×24 PTY terminal with complete VT100/xterm emulation powered by [pyte](https://github.com/selectel/pyte) — correct rendering for Textual-based TUI apps including MeshTTY

**Right panel:** Network status and IP, rotating wireframe globe (location configurable), network traffic oscilloscope, interface list

**Bottom left:** Filesystem browser with folder/file icons, current path, disk usage bar

**Bottom right:** Keyboard visualizer with per-key highlight on keypress

---

## Hardware

| Component | Requirement |
|-----------|-------------|
| Board | Raspberry Pi Zero 2 W (or any Pi) |
| Display | HDMI monitor — tested at 1366×768 |
| OS | Raspberry Pi OS Lite or Desktop (Debian Trixie/Bookworm) |
| Python | 3.11+ |
| RAM | ~30MB at runtime |

---

## Dependencies

| Package | Source | Purpose |
|---------|--------|---------|
| `python3-pygame` | apt | Display, input, SDL2 rendering |
| `python3-psutil` | apt | System stats (CPU, RAM, disk, net) |
| `fonts-dejavu` | apt | UI and terminal font |
| `pyte` | pip | VT100/xterm terminal emulator backend |

---

## Installation

```bash
git clone https://github.com/kendelmccarley/MeshDEX.git
cd MeshDEX
bash install.sh
```

The installer handles apt packages, pyte, swap, bash config, and optional kiosk autostart.

### Manual install

```bash
sudo apt install -y python3-pygame python3-psutil fonts-dejavu
pip3 install pyte --break-system-packages
chmod +x meshdex.py launch.sh
```

---

## Running

```bash
./launch.sh
```

Or directly from SSH:

```bash
DISPLAY=:0 python3 meshdex.py
```

### MeshTTY auto-launch

If `~/MeshTTY/launch-pi.sh` exists, MeshDEX automatically runs it in the terminal pane 1.5 seconds after startup.

```bash
git clone https://github.com/kendelmccarley/MeshTTY.git ~/MeshTTY
cd ~/MeshTTY && bash install-pi.sh
```

---

## Keyboard

| Key | Action |
|-----|--------|
| `Alt+Q` | Quit MeshDEX |
| All other keys | Passed through to the terminal |

All keystrokes — Tab, Shift+Tab, Ctrl+T, Ctrl+Q, Ctrl+R, F1–F12, PageUp/Down, arrow keys — are forwarded unmodified to whatever is running in the terminal. MeshTTY's full keyboard navigation works normally.

---

## Terminal Emulator

MeshDEX uses [pyte](https://github.com/selectel/pyte) as its terminal emulator backend — a battle-tested pure-Python VT100/xterm screen emulator used in production terminal projects.

The terminal pane is sized at exactly **80 columns × 24 rows** to match MeshTTY's expected dimensions. Font size is automatically calculated to fill the available area with centered margins.

Supported:
- Full cursor addressing and movement
- ANSI 16-color, 256-color, and 24-bit RGB
- Reverse video, bold, dim
- Box-drawing characters
- Screen clear and scroll
- All escape sequences Textual/MeshTTY uses

---

## Configuration

Edit the top section of `meshdex.py`:

```python
FPS = 12        # Framerate — 12 is smooth on Pi Zero 2 W
```

### Globe location

Default: Tucson, AZ (32.2°N, 110.9°W). Find the `Globe` class `__init__`:

```python
self.lat = 32.2    # Your latitude
self.lon = -110.9  # Your longitude
```

### Layout proportions

Defined as fractions of screen size — auto-adapts to any resolution:

```python
LEFT_W  = int(W * 0.168)   # Left panel
RIGHT_W = int(W * 0.176)   # Right panel
FS_H    = int(H * 0.286)   # Filesystem/keyboard strip height
KB_W    = int(W * 0.527)   # Keyboard width
```

---

## Kiosk / Auto-start

### 1. Disable the taskbar

```bash
mkdir -p ~/.config/labwc
cat > ~/.config/labwc/autostart << 'AUTOEOF'
/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &
/usr/bin/kanshi &
/usr/bin/lxsession-xdg-autostart
AUTOEOF
```

### 2. Add MeshDEX to autostart

```bash
echo "sleep 2 && /home/digits/MeshDEX/launch.sh &" >> ~/.config/labwc/autostart
```

### 3. Disable bracketed paste

```bash
echo 'bind "set enable-bracketed-paste off"' >> ~/.bashrc
```

The install script handles all of the above automatically.

---

## Performance

- **RAM:** ~30MB (vs ~400MB for Electron-based eDEX-UI)
- **CPU:** 15–30% on Pi Zero 2 W at 12 FPS
- **GPU:** SDL2 software blitting only — no GPU acceleration needed
- **Stats polling:** background thread, every 3 seconds
- **Swap:** 2GB swapfile recommended on Pi Zero 2 W

---

## Known Issues

- **Fork deprecation warning** — Python 3.13 warns about `os.fork()` in multithreaded processes. Harmless — the PTY works correctly.
- **Font size** — Hardcoded for 1366×768. Other resolutions auto-calculate but may need tuning.
- **Globe** — Simplified polyline coastlines, not GIS-accurate.
- **Unicode** — Wide/double-width Unicode characters may misalign columns.

---

## Architecture

```
meshdex.py
├── Stats      — psutil polling thread (3s interval)
├── Terminal   — PTY fork + pyte VT100 screen buffer
├── FS         — Filesystem browser (os.scandir)
├── Globe      — Rotating wireframe Earth (pygame primitives)
├── Keyboard   — Key layout renderer + press highlight
└── main()     — pygame event loop + SDL2 rendering at 12 FPS
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Related

- [MeshTTY](https://github.com/kendelmccarley/MeshTTY) — Meshtastic TUI client (runs inside MeshDEX)
- [Meshtastic](https://meshtastic.org/) — LoRa mesh radio firmware
- [eDEX-UI](https://github.com/GitSquared/edex-ui) — Original inspiration (Electron, desktop hardware required)
- [pyte](https://github.com/selectel/pyte) — Python VT100 terminal emulator
