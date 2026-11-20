#!/usr/bin/env python3
"""
GPUpanel Cinnamon Desktop & Panel Applet Integration Manager
Handles installing, enabling, disabling, and querying the GPUpanel
Cinnamon Panel Applet (gpupanel@cinnamon) and Cinnamon Desktop Desklet (gpupanel@cinnamon).
"""

import glob
import json
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Dict, Optional

import gi
from gi.repository import Gio


APPLET_UUID = "gpupanel@cinnamon"
DESKLET_UUID = "gpupanel-desklet@cinnamon"


class CinnamonAppletManager:
    """Manages installation and live activation of GPUpanel Cinnamon Applet & Desklet."""

    def __init__(self, repo_dir: Optional[str] = None):
        self.repo_dir = repo_dir or os.path.dirname(os.path.abspath(__file__))
        self.applet_src = os.path.join(self.repo_dir, "cinnamon_applet", APPLET_UUID)
        self.desklet_src = os.path.join(self.repo_dir, "cinnamon_desklet", DESKLET_UUID)

        self.applet_dest = os.path.expanduser(f"~/.local/share/cinnamon/applets/{APPLET_UUID}")
        self.desklet_dest = os.path.expanduser(f"~/.local/share/cinnamon/desklets/{DESKLET_UUID}")
        self.icon_src = os.path.join(self.repo_dir, "gpupanel.svg")

    def install_files(self) -> Dict[str, bool]:
        """Copy applet and desklet bundles into ~/.local/share/cinnamon/{applets,desklets}/."""
        res = {"applet_installed": False, "desklet_installed": False}
        try:
            if os.path.isdir(self.applet_src):
                os.makedirs(os.path.dirname(self.applet_dest), exist_ok=True)
                if os.path.exists(self.applet_dest):
                    shutil.rmtree(self.applet_dest)
                shutil.copytree(self.applet_src, self.applet_dest)
                if os.path.isfile(self.icon_src):
                    shutil.copy2(self.icon_src, os.path.join(self.applet_dest, "icon.svg"))
                res["applet_installed"] = True
        except Exception:
            pass

        try:
            if os.path.isdir(self.desklet_src):
                os.makedirs(os.path.dirname(self.desklet_dest), exist_ok=True)
                if os.path.exists(self.desklet_dest):
                    shutil.rmtree(self.desklet_dest)
                shutil.copytree(self.desklet_src, self.desklet_dest)
                if os.path.isfile(self.icon_src):
                    shutil.copy2(self.icon_src, os.path.join(self.desklet_dest, "icon.svg"))
                res["desklet_installed"] = True
        except Exception:
            pass

        return res

    @staticmethod
    def reload_xlets():
        """Hot-reload the GPUpanel desklet and panel applet via Cinnamon DBus."""
        for uuid, kind in ((DESKLET_UUID, "DESKLET"), (APPLET_UUID, "APPLET")):
            try:
                subprocess.run(
                    [
                        "gdbus",
                        "call",
                        "--session",
                        "--dest",
                        "org.Cinnamon",
                        "--object-path",
                        "/org/Cinnamon",
                        "--method",
                        "org.Cinnamon.ReloadXlet",
                        uuid,
                        kind,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    check=False,
                )
            except Exception:
                pass

    def is_applet_enabled(self) -> bool:
        try:
            settings = Gio.Settings.new("org.cinnamon")
            enabled = list(settings.get_strv("enabled-applets"))
            return any(APPLET_UUID in item for item in enabled)
        except Exception:
            return False

    def is_desklet_enabled(self) -> bool:
        try:
            settings = Gio.Settings.new("org.cinnamon")
            enabled = list(settings.get_strv("enabled-desklets"))
            return any(item.startswith(f"{DESKLET_UUID}:") for item in enabled)
        except Exception:
            return False

    def set_applet_enabled(self, enable: bool) -> bool:
        """Enable or disable the GPUpanel applet on the Cinnamon panel."""
        self.install_files()
        try:
            settings = Gio.Settings.new("org.cinnamon")
            enabled = list(settings.get_strv("enabled-applets"))
            currently_on = any(APPLET_UUID in item for item in enabled)

            if enable and not currently_on:
                max_id = 15
                for entry in enabled:
                    parts = entry.split(":")
                    if len(parts) >= 5 and parts[-1].isdigit():
                        max_id = max(max_id, int(parts[-1]))
                next_id = max_id + 1
                # Place on panel1 right side before systray/notifications
                new_entry = f"panel1:right:1:{APPLET_UUID}:{next_id}"
                enabled.append(new_entry)
                settings.set_strv("enabled-applets", enabled)
                return True
            elif not enable and currently_on:
                enabled = [e for e in enabled if APPLET_UUID not in e]
                settings.set_strv("enabled-applets", enabled)
                return True
            return True
        except Exception:
            return False

    def set_desklet_enabled(self, enable: bool, x: int = 2050, y: int = 420) -> bool:
        """Enable or disable the GPUpanel live resource graph desklet on the Cinnamon desktop."""
        self.install_files()
        try:
            settings = Gio.Settings.new("org.cinnamon")
            enabled = [
                e for e in settings.get_strv("enabled-desklets")
                if not e.startswith("gpupanel@cinnamon:")
            ]
            currently_on = any(item.startswith(f"{DESKLET_UUID}:") for item in enabled)

            if enable and not currently_on:
                max_id = 10
                for entry in enabled:
                    parts = entry.split(":")
                    if len(parts) >= 2 and parts[1].isdigit():
                        max_id = max(max_id, int(parts[1]))
                next_id = max_id + 1
                new_entry = f"{DESKLET_UUID}:{next_id}:{x}:{y}"
                enabled.append(new_entry)
                settings.set_strv("enabled-desklets", enabled)
                return True
            elif not enable and currently_on:
                enabled = [e for e in enabled if not e.startswith(f"{DESKLET_UUID}:")]
                settings.set_strv("enabled-desklets", enabled)
                return True
            return True
        except Exception:
            return False

    @staticmethod
    def _atomic_write_json(cfg_path: str, data: dict) -> None:
        if not cfg_path or "\x00" in cfg_path:
            raise ValueError("Invalid JSON config path.")
        abs_path = os.path.abspath(cfg_path)
        st = os.lstat(abs_path)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"Refusing to overwrite non-regular config file: {abs_path}")
        existing_mode = stat.S_IMODE(st.st_mode) & 0o777
        parent_dir = os.path.dirname(abs_path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".gpupanel_cfg_", suffix=".json", dir=parent_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.chmod(tmp_path, existing_mode)
            os.replace(tmp_path, abs_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def set_desklet_dimensions(self, width: int, height: int) -> bool:
        """Update the GPUpanel desktop desklet width and height in Cinnamon spices config and reload it."""
        safe_w = max(120, min(1920, int(width)))
        safe_h = max(80, min(1080, int(height)))
        cfg_dir = os.path.expanduser(f"~/.config/cinnamon/spices/{DESKLET_UUID}")
        updated = False
        if os.path.isdir(cfg_dir):
            for cfg_path in glob.glob(os.path.join(cfg_dir, "*.json")):
                try:
                    st = os.lstat(cfg_path)
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        continue
                    if "desklet-width" in data and isinstance(data["desklet-width"], dict):
                        data["desklet-width"]["value"] = safe_w
                    if "desklet-height" in data and isinstance(data["desklet-height"], dict):
                        data["desklet-height"]["value"] = safe_h
                    if "scale-size" in data and isinstance(data["scale-size"], dict):
                        data["scale-size"]["value"] = 1.0
                    self._atomic_write_json(cfg_path, data)
                    updated = True
                except Exception:
                    pass
        if updated:
            self.reload_xlets()
        return updated

    def pin_to_cinnamon_panel_and_favorites(self) -> bool:
        """Add gpupanel.desktop to Cinnamon favorite-apps and grouped-window-list pinned apps."""
        ok = False
        try:
            settings = Gio.Settings.new("org.cinnamon")
            favs = list(settings.get_strv("favorite-apps"))
            if "gpupanel.desktop" not in favs:
                favs.append("gpupanel.desktop")
                settings.set_strv("favorite-apps", favs)
            ok = True
        except Exception:
            pass

        for cfg_path in glob.glob(
            os.path.expanduser("~/.config/cinnamon/spices/grouped-window-list@cinnamon.org/*.json")
        ):
            try:
                st = os.lstat(cfg_path)
                if not stat.S_ISREG(st.st_mode):
                    continue
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                pinned = data.get("pinned-apps", {}).get("value")
                if isinstance(pinned, list) and "gpupanel.desktop" not in pinned:
                    pinned.append("gpupanel.desktop")
                    self._atomic_write_json(cfg_path, data)
                ok = True
            except Exception:
                pass
        return ok
