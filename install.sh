#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN_DIR="$HOME/.local/bin"
APPLETS_DIR="$HOME/.local/share/cinnamon/applets"
DESKLETS_DIR="$HOME/.local/share/cinnamon/desklets"

echo "=========================================================="
echo " Installing GPUpanel for Linux Mint Cinnamon"
echo " (GPU Resource Graph App + Panel Applet + Desklet)"
echo "=========================================================="

chmod +x "$DIR/run.sh" "$DIR/gpupanel.py" "$DIR/gpu_telemetry.py" "$DIR/gpu_graphs.py" "$DIR/cinnamon_manager.py"

mkdir -p "$APP_DIR" "$ICONS_DIR" "$BIN_DIR" "$HOME/.icons" "$HOME/.local/share/pixmaps" "$APPLETS_DIR" "$DESKLETS_DIR"

# 1. Install high-DPI vector icon & multi-size PNG icons
cp -f "$DIR/gpupanel.svg" "$ICONS_DIR/gpupanel.svg"
cp -f "$DIR/gpupanel.svg" "$HOME/.icons/gpupanel.svg"
cp -f "$DIR/gpupanel.svg" "$HOME/.local/share/pixmaps/gpupanel.svg"

python3 -B -c "
import os, gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
src = '$DIR/gpupanel.svg'
base = os.path.expanduser('~/.local/share/icons/hicolor')
for sz in (16, 24, 32, 48, 64, 128, 256, 512):
    out_dir = os.path.join(base, f'{sz}x{sz}', 'apps')
    os.makedirs(out_dir, exist_ok=True)
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, sz, sz, True)
    pb.savev(os.path.join(out_dir, 'gpupanel.png'), 'png', [], [])
" 2>/dev/null || true

echo "[+] Installed GPUpanel SVG & panel icon set: $ICONS_DIR/gpupanel.svg"

# 2. Install CLI symlink in ~/.local/bin
ln -sf "$DIR/run.sh" "$BIN_DIR/gpupanel"
echo "[+] Created CLI executable link: $BIN_DIR/gpupanel"

# 3. Install Desktop Entry for Cinnamon Menu & Panel
cat <<EOF > "$APP_DIR/gpupanel.desktop"
[Desktop Entry]
Name=GPUpanel
Comment=GPU resource graph workstation, Cinnamon panel applet, and desktop graph desklet in PythonPanel neon style
GenericName=GPU Resource Monitor
Exec=$DIR/run.sh %F
Icon=$ICONS_DIR/gpupanel.svg
Terminal=false
Type=Application
Categories=GTK;GNOME;System;Monitor;HardwareSettings;Utility;
StartupNotify=true
StartupWMClass=gpupanel
Keywords=gpu;cuda;vram;graph;telemetry;monitor;applet;desklet;gpupanel;rtx;
Actions=MiniHUD;NewWindow;

[Desktop Action MiniHUD]
Name=Open Compact Floating Mini HUD
Exec=$DIR/run.sh --hud

[Desktop Action NewWindow]
Name=Open a New Window
Exec=$DIR/run.sh
EOF

chmod +x "$APP_DIR/gpupanel.desktop"
echo "[+] Installed desktop entry: $APP_DIR/gpupanel.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# 4. Install and enable Cinnamon Panel Applet, Desktop Graph Desklet, Favorites, and Panel Pin
python3 -B -c "
import sys
sys.path.insert(0, '$DIR')
from cinnamon_manager import CinnamonAppletManager

mgr = CinnamonAppletManager('$DIR')
res = mgr.install_files()
print('[+] Installed Cinnamon Panel Applet:  ~/.local/share/cinnamon/applets/gpupanel@cinnamon')
print('[+] Installed Cinnamon Desktop Desklet: ~/.local/share/cinnamon/desklets/gpupanel-desklet@cinnamon')

mgr.set_applet_enabled(False)
if mgr.set_applet_enabled(True):
    print('[+] Enabled GPUpanel Applet on Cinnamon Panel (gpupanel@cinnamon)')
mgr.set_desklet_enabled(False)
if mgr.set_desklet_enabled(True, x=2050, y=420):
    print('[+] Enabled GPUpanel Live Graph Desklet on Cinnamon Desktop (gpupanel-desklet@cinnamon)')
if mgr.pin_to_cinnamon_panel_and_favorites():
    print('[+] Pinned GPUpanel to Cinnamon Favorites and grouped-window-list Panel')
mgr.reload_xlets()
" || true

echo ""
echo "=========================================================="
echo " GPUpanel Installation Complete!"
echo "=========================================================="
echo "1. Full App: Launch 'GPUpanel' from Cinnamon Menu or run:"
echo "     gpupanel"
echo "2. Mini Floating HUD: Launch compact always-on-top mode:"
echo "     gpupanel --hud"
echo "3. Cinnamon Panel Applet: Active in your bottom panel bar"
echo "   (gpupanel@cinnamon - click it for live telemetry popup)."
echo "4. Cinnamon Desktop Graph Desklet: Active on your desktop"
echo "   (gpupanel@cinnamon - click it anytime to open GPUpanel)."
echo "=========================================================="
