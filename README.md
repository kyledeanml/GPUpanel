# GPUpanel

<p align="center">
  <img src="gpupanel.svg" alt="GPUpanel Logo" width="160" height="160">
</p>

A fast, modern **GPU Resource Graph Workstation**, **Cinnamon Panel Bar Applet**, and **Cinnamon Desktop Graph Desklet** with **Retina Vision** (HiDPI subpixel anti-aliased Cairo oscilloscopes), **6x Radial Neon Gauges**, **Active GPU Process & VRAM Inspector**, and **Direct Low-Overhead Hardware Telemetry**, built natively for **Linux Mint Cinnamon** in the **PythonPanel Dark Neon** aesthetic.

---

## Key Features

### 1. Direct Low-Overhead Hardware Telemetry
- **Zero-Subprocess Overhead**: Queries the GPU management library directly via `ctypes` at up to **4 Hz (250 ms)** with automatic fallback to CLI sensor polling or synthetic simulation.
- **Comprehensive Real-Time Channels**:
  - **GPU Core (SM) Load (`%`)** & **Memory Controller Bus Load (`%`)**
  - **VRAM Allocation (`MiB`, `GiB`, `%`)** with per-process segmented breakdown
  - **GPU Die Temperature (`°C`)**, Slowdown/Shutdown thermal margins, & **Cooling Fan Duty (`%`)**
  - **Board Power Draw (`W`)** vs TDP Power Limit (`W` & `%`)
  - **Graphics / SM Boost Clocks (`MHz`)** & **Memory Clocks (`MHz`)**
  - **PCIe Link Generation, Width (`Gen4 x16`), & Live TX/RX Bandwidth (`MB/s`)**
  - **Video Encoder (`ENC %`) & Decoder (`DEC %`)** utilization
  - **Performance State (`P0`..`P8`)** badge

### 2. Retina Vision Cairo Oscilloscopes & Radial Neon Gauges
- **6x Radial Neon Gauge Strip**: Live circular arc gauges with embedded 48-point sparklines for GPU Core, VRAM, Thermal, Power Draw, Cooling Fan, and Core Clock.
- **6-Card Split Resource Graph Grid**: Dedicated dual- and single-channel Cairo graphs for Core/MemBus, VRAM, Thermal/Fan, Power, Clocks, and auto-scaling PCIe Bandwidth.
- **Combined Multi-Channel Oscilloscope**: Full-bleed multi-trace oscilloscope with interactive mouse hover crosshair tooltip showing exact timestamped metrics.
- **Dynamic Retina Zooming**: Scale typography and graph chrome smoothly from **70% to 200%** (`Ctrl + +`, `Ctrl + -`, `Ctrl + 0`, or `Ctrl + Scroll Wheel`).

### 3. Active GPU Processes & Segmented VRAM Inspector
- **Segmented Neon VRAM Bar**: Visualizes how much VRAM is consumed by each active Graphics (`G`) or Compute (`C` / `C+G`) process versus free VRAM.
- **Live Process Table**: Inspect PID, Engine (`G`, `C`, `C+G`), Process Name, User, VRAM (`MiB` & `%`), and full Command Line, with instant search filtering, clipboard copy, and `SIGTERM` process termination.

### 4. Native Linux Mint Cinnamon Desktop & Panel Applets Included
- **Cinnamon Panel Bar Applet (`gpupanel@cinnamon`)**:
  - Installed into `~/.local/share/cinnamon/applets/gpupanel@cinnamon`.
  - Renders a live mini Cairo graph (`GPU%` + `VRAM%`) directly inside your Cinnamon panel bar alongside live `GPU% · VRAM · Temp°C` readouts and a Dark Neon popup oscilloscope menu.
- **Cinnamon Desktop Graph Desklet (`gpupanel-desklet@cinnamon`)**:
  - Installed into `~/.local/share/cinnamon/desklets/gpupanel-desklet@cinnamon`.
  - Renders a live PythonPanel Dark Neon GPU resource graph widget directly on your desktop wallpaper; drag its bottom-right corner grip (`◢`) or use `Ctrl + Scroll Wheel` to resize it freely, and click it anytime to launch the full **GPUpanel** app.
- **Compact Floating Mini HUD (`F10` or `gpupanel --hud`)**:
  - Converts the GPUpanel window into an always-on-top compact floating HUD oscilloscope.

---

## Installation

```bash
cd ~/gpupanel
./install.sh
```

The installer automatically:
- Installs the vector icon (`gpupanel.svg`) and multi-size PNG icons into `~/.local/share/icons/hicolor/`.
- Creates the `~/.local/bin/gpupanel` CLI command and `~/.local/share/applications/gpupanel.desktop` launcher.
- Pins **GPUpanel** to Cinnamon Favorites and the `grouped-window-list` panel taskbar.
- Installs and enables both the **Cinnamon Panel Applet** (`gpupanel@cinnamon`) and **Cinnamon Desktop Graph Desklet** (`gpupanel-desklet@cinnamon`).

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Space` | **Pause / Resume Live Telemetry Graphs** |
| `F10` | **Toggle Compact Always-on-Top Mini HUD Mode** |
| `Ctrl + B` / `F9` | **Toggle Left Telemetry Control Sidebar** |
| `Ctrl + R` | **Reset Graph History & Peak Counters** |
| `Ctrl + +` / `Ctrl + -` | **Retina Zoom In / Out** |
| `Ctrl + 0` | **Reset Retina Zoom (100%)** |
| `Ctrl + Scroll Wheel` | **Smooth Real-Time Retina Zooming** |
| `Ctrl + Q` | **Quit GPUpanel** |
