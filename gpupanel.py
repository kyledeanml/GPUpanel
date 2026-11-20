#!/usr/bin/env python3
"""
GPUpanel - GPU Resource Graph & Telemetry Workstation
With Retina Vision Cairo Oscilloscope Graphs, Radial Neon Gauges,
Active GPU Process Inspector, Mini Floating HUD Mode, and
Native Linux Mint Cinnamon Panel Applet & Desktop Desklet Integration.
Built in the PythonPanel Dark Neon aesthetic.
"""

import os
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional

sys.dont_write_bytecode = True
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, Gdk, GdkPixbuf, Pango, GLib, Gio

from gpu_telemetry import (
    GpuTelemetryEngine,
    GpuHistoryBuffer,
    GpuSnapshot,
    GpuDeviceSpec,
    METRIC_CHANNELS,
)
from gpu_graphs import GpuGaugeCard, GpuResourceGraph, VramAllocationBar
from cinnamon_manager import CinnamonAppletManager


class GpuPanelWindow(Gtk.ApplicationWindow):
    """Main application window for GPUpanel."""

    APP_NAME = "GPUpanel"
    APP_VERSION = "1.0"

    def __init__(self, app, start_hud: bool = False):
        super().__init__(application=app, title=self.APP_NAME)
        self.set_default_size(1220, 780)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Telemetry engine & state
        self.engine = GpuTelemetryEngine()
        self.cinnamon_mgr = CinnamonAppletManager()
        self.current_gpu_index: int = 0
        self.poll_interval_ms: int = 500
        self.is_paused: bool = False
        self.is_hud_mode: bool = False
        self.zoom_pct: int = 100
        self.history = GpuHistoryBuffer(max_points=180)
        self._timer_id: Optional[int] = None

        # Set WMClass and high-DPI icon for Cinnamon panel & window grouping
        self.set_wmclass("gpupanel", "GPUpanel")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpupanel.svg")
        if os.path.exists(icon_path):
            try:
                Gtk.Window.set_default_icon_from_file(icon_path)
                self.set_icon_from_file(icon_path)
                pixbufs = [
                    GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, sz, sz, True)
                    for sz in (16, 24, 32, 48, 64, 128, 256)
                ]
                Gtk.Window.set_default_icon_list(pixbufs)
                self.set_icon_list(pixbufs)
            except Exception:
                pass

        # Dark mode preference & PythonPanel Dark Neon CSS theme
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        self._apply_dark_neon_theme()

        # Build UI
        self._build_header_bar()
        self._build_main_layout()
        self._build_status_bar()
        self._setup_shortcuts()

        self.connect("delete-event", self._on_delete_event)
        self.connect("scroll-event", self._on_scroll_zoom)

        # Seed initial telemetry snapshot
        self._poll_once()
        self._restart_timer()

        self.show_all()
        if start_hud:
            self.toggle_hud_mode(True)

    # ------------------------------------------------------------------
    # PythonPanel Dark Neon Theme
    # ------------------------------------------------------------------
    def _apply_dark_neon_theme(self):
        css = b"""
        /* GPUpanel / PythonPanel Dark Neon Theme */
        window, dialog, .background {
            background-color: #0b0f19;
            color: #ffffff;
        }

        headerbar {
            background: linear-gradient(to bottom, #111827, #0b0f19);
            border-bottom: 1px solid rgba(0, 240, 255, 0.35);
            box-shadow: 0 1px 6px rgba(0, 240, 255, 0.12);
            color: #ffffff;
            padding: 4px 6px;
        }
        headerbar .title {
            color: #ffffff;
            font-weight: bold;
        }
        headerbar .subtitle {
            color: #38bdf8;
            font-size: 85%;
        }

        button, combobox button {
            background-color: #131d33;
            color: #ffffff;
            border: 1px solid rgba(0, 240, 255, 0.25);
            border-radius: 4px;
            padding: 4px 8px;
            transition: all 150ms ease;
        }
        button:hover, combobox button:hover {
            background-color: #1a2744;
            border-color: #00f0ff;
            color: #00f0ff;
            box-shadow: 0 0 6px rgba(0, 240, 255, 0.35);
        }
        button:checked, button:active {
            background-color: #034b75;
            border-color: #00f0ff;
            color: #ffffff;
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.45);
        }

        .applet-active-btn {
            background-color: #053b47;
            border-color: #00f0ff;
            color: #00f0ff;
            font-weight: bold;
        }

        .pstate-badge {
            background-color: #0d1f38;
            color: #00f0ff;
            border: 1px solid rgba(0, 240, 255, 0.55);
            border-radius: 4px;
            padding: 3px 8px;
            font-family: monospace;
            font-weight: bold;
        }

        notebook {
            background-color: #070a14;
        }
        notebook > header {
            background-color: #070a14;
            border-bottom: 1px solid rgba(0, 240, 255, 0.2);
        }
        notebook tab {
            background-color: #0b0f19;
            color: #94a3b8;
            border: 1px solid rgba(0, 240, 255, 0.15);
            border-bottom: none;
            padding: 6px 14px;
            margin-right: 2px;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
        }
        notebook tab:hover {
            background-color: #131d33;
            color: #e0f2fe;
            border-color: rgba(0, 240, 255, 0.4);
        }
        notebook tab:checked {
            background-color: #0a0e1a;
            color: #ffffff;
            border-color: #00f0ff;
            border-top: 2px solid #00f0ff;
            box-shadow: inset 0 2px 0 #00f0ff;
        }
        notebook tab label {
            color: inherit;
            font-weight: 600;
        }

        paned > separator {
            background-color: #070a14;
            border: 1px solid rgba(0, 240, 255, 0.25);
            min-height: 4px;
            min-width: 4px;
        }
        paned > separator:hover {
            background-color: #00f0ff;
        }

        .sidebar-box {
            background-color: #080c16;
            border-right: 1px solid rgba(0, 240, 255, 0.25);
        }
        .sidebar-header {
            background-color: #0d1322;
            border-bottom: 1px solid rgba(0, 240, 255, 0.2);
            padding: 6px 10px;
        }
        .sidebar-title {
            color: #00f0ff;
            font-size: 88%;
            font-weight: bold;
            letter-spacing: 0.5px;
        }
        .neon-card {
            background-color: #0d1322;
            border: 1px solid rgba(0, 240, 255, 0.25);
            border-radius: 6px;
            padding: 8px 10px;
        }

        .statusbar, #statusbar {
            background-color: #070a14;
            border-top: 1px solid rgba(0, 240, 255, 0.2);
            color: #94a3b8;
            padding: 3px 10px;
        }
        .statusbar label, #statusbar label {
            color: #cbd5e1;
            font-family: monospace;
            font-size: 88%;
        }

        entry {
            background-color: #0a0e1a;
            color: #ffffff;
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 4px;
            padding: 4px 8px;
        }
        entry:focus {
            border-color: #00f0ff;
        }

        menu, .menu {
            background-color: #0d1322;
            color: #ffffff;
            border: 1px solid rgba(0, 240, 255, 0.35);
            padding: 4px;
        }
        menuitem {
            color: #e0f2fe;
            padding: 5px 10px;
        }
        menuitem:hover {
            background-color: #034b75;
            color: #ffffff;
        }

        treeview {
            background-color: #0a0e1a;
            color: #f8fafc;
            font-family: monospace;
        }
        treeview:selected {
            background-color: #034b75;
            color: #ffffff;
        }
        treeview header button {
            background-color: #0d1322;
            color: #00f0ff;
            border-bottom: 1px solid rgba(0, 240, 255, 0.3);
            font-weight: bold;
        }

        scrollbar {
            background-color: #070a14;
        }
        scrollbar slider {
            background-color: #1e293b;
            border-radius: 4px;
            min-width: 8px;
            min-height: 8px;
        }
        scrollbar slider:hover {
            background-color: #0284c7;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    # ------------------------------------------------------------------
    # Header Bar
    # ------------------------------------------------------------------
    def _build_header_bar(self):
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        spec = self.engine.get_device_spec(0)
        self.header.set_title(self.APP_NAME)
        self.header.set_subtitle(f"{spec.name} · Driver {spec.driver_version} · CUDA {spec.cuda_version}")
        self.set_titlebar(self.header)

        # Left Controls: Sidebar Toggle + GPU Selector + PState Badge
        self.btn_sidebar = Gtk.ToggleButton()
        self.btn_sidebar.set_active(True)
        self.btn_sidebar.set_tooltip_text("Toggle Telemetry Sidebar (Ctrl+B / F9)")
        self.btn_sidebar.set_image(
            Gtk.Image.new_from_icon_name("view-dual-symbolic", Gtk.IconSize.BUTTON)
        )
        self.btn_sidebar.connect("toggled", self._on_sidebar_toggled)
        self.header.pack_start(self.btn_sidebar)

        # GPU selector ComboBox
        self.gpu_combo = Gtk.ComboBoxText()
        self.gpu_combo.set_tooltip_text("Select GPU Device")
        for s in self.engine.specs:
            short_name = s.name.replace("GeForce ", "")
            self.gpu_combo.append_text(f"GPU {s.index}: {short_name}")
        self.gpu_combo.set_active(0)
        self.gpu_combo.connect("changed", self._on_gpu_changed)
        self.header.pack_start(self.gpu_combo)

        # Live PState badge
        self.lbl_pstate = Gtk.Label(label="P0")
        self.lbl_pstate.get_style_context().add_class("pstate-badge")
        self.lbl_pstate.set_tooltip_text("GPU Performance State (P0 = Max Performance, P8 = Idle)")
        self.header.pack_start(self.lbl_pstate)

        # Refresh interval selector
        self.rate_combo = Gtk.ComboBoxText()
        self.rate_combo.set_tooltip_text("Telemetry Sampling Rate")
        for label in ("250 ms (4 Hz)", "500 ms (2 Hz)", "1.0 s (1 Hz)", "2.0 s (0.5 Hz)"):
            self.rate_combo.append_text(label)
        self.rate_combo.set_active(1)  # 500 ms default
        self.rate_combo.connect("changed", self._on_rate_changed)
        self.header.pack_start(self.rate_combo)

        # Pause / Resume toggle
        self.btn_pause = Gtk.ToggleButton(label="Pause")
        self.btn_pause.set_tooltip_text("Pause / Resume Live Telemetry Graphs (Space)")
        self.btn_pause.connect("toggled", self._on_pause_toggled)
        self.header.pack_start(self.btn_pause)

        # Right Controls: Menu + Zoom + Mini HUD + Desktop/Panel Applet Manager
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_image(
            Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        )
        self.menu_btn.set_tooltip_text("GPUpanel Options & Telemetry Export")
        self.menu_btn.set_popup(self._build_app_menu())
        self.header.pack_end(self.menu_btn)

        # Retina Zoom box
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        zoom_box.get_style_context().add_class("linked")

        btn_z_out = Gtk.Button(label="−")
        btn_z_out.set_tooltip_text("Retina Zoom Out (Ctrl+-)")
        btn_z_out.connect("clicked", lambda *_: self.adjust_zoom(-10))

        self.btn_z_reset = Gtk.Button(label="100%")
        self.btn_z_reset.set_tooltip_text("Reset Retina Zoom (Ctrl+0)")
        self.btn_z_reset.connect("clicked", lambda *_: self.set_zoom(100))

        btn_z_in = Gtk.Button(label="+")
        btn_z_in.set_tooltip_text("Retina Zoom In (Ctrl++)")
        btn_z_in.connect("clicked", lambda *_: self.adjust_zoom(10))

        zoom_box.pack_start(btn_z_out, False, False, 0)
        zoom_box.pack_start(self.btn_z_reset, False, False, 0)
        zoom_box.pack_start(btn_z_in, False, False, 0)
        self.header.pack_end(zoom_box)

        # Floating Mini HUD toggle
        self.btn_hud = Gtk.ToggleButton(label="Mini HUD")
        self.btn_hud.set_tooltip_text("Toggle Compact Always-on-Top Floating Desktop HUD (F10)")
        self.btn_hud.connect("toggled", lambda btn: self.toggle_hud_mode(btn.get_active()))
        self.header.pack_end(self.btn_hud)

        # Desktop & Panel Applet Installer / Manager Button
        self.btn_applet_mgr = Gtk.Button(label="Desktop Applet")
        self.btn_applet_mgr.set_tooltip_text(
            "Install or toggle the GPUpanel Cinnamon Panel Applet & Desktop Graph Desklet"
        )
        self.btn_applet_mgr.connect("clicked", lambda *_: self._show_cinnamon_applet_dialog())
        self.header.pack_end(self.btn_applet_mgr)
        self._refresh_applet_button_style()

    def _build_app_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        item_applet = Gtk.MenuItem(label="Cinnamon Desktop & Panel Applet Manager...")
        item_applet.connect("activate", lambda *_: self._show_cinnamon_applet_dialog())
        menu.append(item_applet)

        item_hud = Gtk.MenuItem(label="Toggle Compact Floating HUD Mode (F10)")
        item_hud.connect("activate", lambda *_: self.btn_hud.set_active(not self.btn_hud.get_active()))
        menu.append(item_hud)

        menu.append(Gtk.SeparatorMenuItem())

        item_csv = Gtk.MenuItem(label="Export Telemetry History to CSV...")
        item_csv.connect("activate", lambda *_: self._export_telemetry("csv"))
        menu.append(item_csv)

        item_json = Gtk.MenuItem(label="Export Telemetry History to JSON...")
        item_json.connect("activate", lambda *_: self._export_telemetry("json"))
        menu.append(item_json)

        item_copy = Gtk.MenuItem(label="Copy GPU Telemetry Summary to Clipboard")
        item_copy.connect("activate", lambda *_: self._copy_gpu_report())
        menu.append(item_copy)

        item_clear = Gtk.MenuItem(label="Reset Graph History & Peak Counters (Ctrl+R)")
        item_clear.connect("activate", lambda *_: self._clear_history())
        menu.append(item_clear)

        menu.append(Gtk.SeparatorMenuItem())

        item_hidpi = Gtk.MenuItem(label="Retina Vision / HiDPI Diagnostics")
        item_hidpi.connect("activate", lambda *_: self._show_retina_info_dialog())
        menu.append(item_hidpi)

        item_about = Gtk.MenuItem(label="About GPUpanel")
        item_about.connect("activate", lambda *_: self._show_about_dialog())
        menu.append(item_about)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit GPUpanel (Ctrl+Q)")
        item_quit.connect("activate", lambda *_: self.close())
        menu.append(item_quit)

        menu.show_all()
        return menu

    # ------------------------------------------------------------------
    # Main Body Layout (Sidebar + Gauges + Multi-Tab Resource Graphs)
    # ------------------------------------------------------------------
    def _build_main_layout(self):
        self.root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(self.root_vbox)

        self.hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.hpaned.set_position(275)
        self.root_vbox.pack_start(self.hpaned, True, True, 0)

        # 1. Left Telemetry & Applet Control Sidebar
        self.sidebar_box = self._build_sidebar()
        self.hpaned.pack1(self.sidebar_box, resize=False, shrink=False)

        # 2. Right Workstation Area
        self.right_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.right_vbox.set_margin_top(8)
        self.right_vbox.set_margin_bottom(8)
        self.right_vbox.set_margin_start(8)
        self.right_vbox.set_margin_end(8)
        self.hpaned.pack2(self.right_vbox, resize=True, shrink=False)

        # Top Strip: 6 Radial Neon Gauge Cards
        self.gauge_grid = Gtk.Grid()
        self.gauge_grid.set_column_spacing(8)
        self.gauge_grid.set_row_spacing(8)
        self.gauge_grid.set_column_homogeneous(True)

        self.gauge_gpu = GpuGaugeCard("GPU Core", "gpu_util", METRIC_CHANNELS["gpu_util"]["rgb"])
        self.gauge_vram = GpuGaugeCard("VRAM Used", "vram_pct", METRIC_CHANNELS["vram_pct"]["rgb"])
        self.gauge_temp = GpuGaugeCard("Thermal", "temp_c", METRIC_CHANNELS["temp_c"]["rgb"])
        self.gauge_pwr = GpuGaugeCard("Power Draw", "power_pct", METRIC_CHANNELS["power_pct"]["rgb"])
        self.gauge_fan = GpuGaugeCard("Cooling Fan", "fan_pct", METRIC_CHANNELS["fan_pct"]["rgb"])
        self.gauge_clk = GpuGaugeCard("Core Clock", "clock_gfx_pct", METRIC_CHANNELS["clock_gfx_pct"]["rgb"])

        self.gauges = [
            self.gauge_gpu,
            self.gauge_vram,
            self.gauge_temp,
            self.gauge_pwr,
            self.gauge_fan,
            self.gauge_clk,
        ]
        for idx, g in enumerate(self.gauges):
            self.gauge_grid.attach(g, idx, 0, 1, 1)

        self.right_vbox.pack_start(self.gauge_grid, False, False, 0)

        # Center Notebook Tabs
        self.notebook = Gtk.Notebook()
        self.right_vbox.pack_start(self.notebook, True, True, 0)

        # Tab 1: 6-Card Split Telemetry Grid
        self.tab_quad_grid = self._build_quad_graphs_tab()
        self.notebook.append_page(
            self.tab_quad_grid,
            Gtk.Label(label="Resource Graph Grid (6x)"),
        )

        # Tab 2: Combined Multi-Channel Oscilloscope
        self.tab_combined = self._build_combined_oscilloscope_tab()
        self.notebook.append_page(
            self.tab_combined,
            Gtk.Label(label="Multi-Channel Oscilloscope"),
        )

        # Tab 3: Active GPU Processes & VRAM Inspector
        self.tab_processes = self._build_processes_tab()
        self.notebook.append_page(
            self.tab_processes,
            Gtk.Label(label="Active GPU Processes & VRAM"),
        )

        # Tab 4: Hardware & Driver Specifications
        self.tab_specs = self._build_specs_tab()
        self.notebook.append_page(
            self.tab_specs,
            Gtk.Label(label="Hardware & Sensor Specs"),
        )

    def _build_sidebar(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.get_style_context().add_class("sidebar-box")
        box.set_size_request(265, -1)

        # Sidebar Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hdr.get_style_context().add_class("sidebar-header")
        lbl_hdr = Gtk.Label(label="GPU TELEMETRY CONTROL")
        lbl_hdr.get_style_context().add_class("sidebar-title")
        lbl_hdr.set_xalign(0.0)
        hdr.pack_start(lbl_hdr, True, True, 0)
        box.pack_start(hdr, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_top(6)
        inner.set_margin_bottom(10)
        inner.set_margin_start(10)
        inner.set_margin_end(10)
        scroll.add(inner)
        box.pack_start(scroll, True, True, 0)

        # 1. Hardware Summary Card
        hw_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hw_card.get_style_context().add_class("neon-card")
        lbl_hw_title = Gtk.Label()
        lbl_hw_title.set_markup("<span foreground='#00f0ff' weight='bold'>ACTIVE GPU DEVICE</span>")
        lbl_hw_title.set_xalign(0.0)
        hw_card.pack_start(lbl_hw_title, False, False, 0)

        self.lbl_hw_summary = Gtk.Label()
        self.lbl_hw_summary.set_xalign(0.0)
        self.lbl_hw_summary.set_selectable(True)
        self.lbl_hw_summary.set_line_wrap(True)
        hw_card.pack_start(self.lbl_hw_summary, False, False, 0)
        inner.pack_start(hw_card, False, False, 0)

        # 2. Cinnamon Desktop & Panel Applet Card
        app_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        app_card.get_style_context().add_class("neon-card")

        lbl_app_title = Gtk.Label()
        lbl_app_title.set_markup("<span foreground='#00f0ff' weight='bold'>CINNAMON DESKTOP APPLETS</span>")
        lbl_app_title.set_xalign(0.0)
        app_card.pack_start(lbl_app_title, False, False, 0)

        # Panel Applet Switch row
        row_panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_p = Gtk.Label(label="Panel Bar Applet")
        lbl_p.set_xalign(0.0)
        lbl_p.set_tooltip_text("Live mini Cairo GPU graph & telemetry popup in your Cinnamon taskbar panel")
        self.sw_panel_applet = Gtk.Switch()
        self.sw_panel_applet.set_active(self.cinnamon_mgr.is_applet_enabled())
        self.sw_panel_applet.connect("notify::active", self._on_panel_applet_switch)
        row_panel.pack_start(lbl_p, True, True, 0)
        row_panel.pack_end(self.sw_panel_applet, False, False, 0)
        app_card.pack_start(row_panel, False, False, 0)

        # Desktop Graph Desklet Switch row
        row_desk = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_d = Gtk.Label(label="Desktop Graph Widget")
        lbl_d.set_xalign(0.0)
        lbl_d.set_tooltip_text("Live PythonPanel-styled GPU resource graph desklet directly on your desktop")
        self.sw_desklet = Gtk.Switch()
        self.sw_desklet.set_active(self.cinnamon_mgr.is_desklet_enabled())
        self.sw_desklet.connect("notify::active", self._on_desklet_switch)
        row_desk.pack_start(lbl_d, True, True, 0)
        row_desk.pack_end(self.sw_desklet, False, False, 0)
        app_card.pack_start(row_desk, False, False, 0)

        # Desktop Graph Size Selector row
        row_sz = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_sz = Gtk.Label(label="Desktop Size")
        lbl_sz.set_xalign(0.0)
        self.combo_desk_size = Gtk.ComboBoxText()
        self.combo_desk_size.set_tooltip_text("Resize the GPUpanel Desktop Graph Widget (or drag its bottom-right corner)")
        self._desk_size_presets = [
            ("Compact (240×125)", 240, 125),
            ("Small (300×150)", 300, 150),
            ("Standard (360×180)", 360, 180),
            ("Wide (420×205)", 420, 205),
            ("Large (480×235)", 480, 235),
            ("XL (560×275)", 560, 275),
        ]
        for label, _w, _h in self._desk_size_presets:
            self.combo_desk_size.append_text(label)
        self.combo_desk_size.set_active(2)
        self.combo_desk_size.connect("changed", self._on_desk_size_preset_changed)
        row_sz.pack_start(lbl_sz, False, False, 0)
        row_sz.pack_end(self.combo_desk_size, True, True, 0)
        app_card.pack_start(row_sz, False, False, 0)

        btn_reinstall_applets = Gtk.Button(label="Sync & Refresh Applets")
        btn_reinstall_applets.set_tooltip_text("Install/update applet & desklet files and pin GPUpanel to panel")
        btn_reinstall_applets.connect("clicked", self._on_sync_applets_clicked)
        app_card.pack_start(btn_reinstall_applets, False, False, 2)

        inner.pack_start(app_card, False, False, 0)

        # 3. Oscilloscope Channel Toggles & Live Peak Readouts
        ch_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        ch_card.get_style_context().add_class("neon-card")
        lbl_ch_title = Gtk.Label()
        lbl_ch_title.set_markup("<span foreground='#00f0ff' weight='bold'>OSCILLOSCOPE CHANNELS</span>")
        lbl_ch_title.set_xalign(0.0)
        ch_card.pack_start(lbl_ch_title, False, False, 0)

        self.channel_stat_labels: Dict[str, Gtk.Label] = {}
        self.channel_checks: Dict[str, Gtk.CheckButton] = {}

        for key, meta in METRIC_CHANNELS.items():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            chk = Gtk.CheckButton()
            chk.set_active(True)
            chk.connect("toggled", self._on_channel_check_toggled, key)
            self.channel_checks[key] = chk

            color_hex = str(meta["color_hex"])
            lbl_name = Gtk.Label()
            lbl_name.set_markup(
                f"<span foreground='{color_hex}' weight='bold'>●</span> <span size='small'>{meta['short']}</span>"
            )
            lbl_name.set_xalign(0.0)

            lbl_val = Gtk.Label(label="0%")
            lbl_val.set_xalign(1.0)
            lbl_val.set_use_markup(True)

            row.pack_start(chk, False, False, 0)
            row.pack_start(lbl_name, False, False, 0)
            row.pack_end(lbl_val, True, True, 0)
            ch_card.pack_start(row, False, False, 0)
            self.channel_stat_labels[key] = lbl_val

        inner.pack_start(ch_card, False, False, 0)

        # 4. Graph Appearance Options
        opt_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        opt_card.get_style_context().add_class("neon-card")
        lbl_opt = Gtk.Label()
        lbl_opt.set_markup("<span foreground='#00f0ff' weight='bold'>GRAPH OPTIONS</span>")
        lbl_opt.set_xalign(0.0)
        opt_card.pack_start(lbl_opt, False, False, 0)

        chk_grid = Gtk.CheckButton(label="Show Oscilloscope Grid")
        chk_grid.set_active(True)
        chk_grid.connect("toggled", self._on_grid_toggled)
        opt_card.pack_start(chk_grid, False, False, 0)

        chk_fill = Gtk.CheckButton(label="Neon Gradient Area Fill")
        chk_fill.set_active(True)
        chk_fill.connect("toggled", self._on_fill_toggled)
        opt_card.pack_start(chk_fill, False, False, 0)

        inner.pack_start(opt_card, False, False, 0)
        return box

    def _build_quad_graphs_tab(self) -> Gtk.Widget:
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        grid.set_margin_start(8)
        grid.set_margin_end(8)

        self.graph_core = GpuResourceGraph(
            title="GPU CORE & MEMORY CONTROLLER LOAD",
            subtitle="SM Compute Engine (%) & Memory Bus Utilization (%)",
            history=self.history,
            channels=["gpu_util", "mem_ctrl_util"],
            y_unit="%",
            fixed_max=100.0,
        )
        self.graph_vram = GpuResourceGraph(
            title="VRAM MEMORY ALLOCATION",
            subtitle="Dedicated Video Memory Usage (% of Total VRAM)",
            history=self.history,
            channels=["vram_pct"],
            y_unit="%",
            fixed_max=100.0,
        )
        self.graph_thermal = GpuResourceGraph(
            title="THERMAL & COOLING FAN PROFILE",
            subtitle="GPU Die Temperature (°C) & Cooling Fan Duty Cycle (%)",
            history=self.history,
            channels=["temp_c", "fan_pct"],
            y_unit="°C",
            fixed_max=100.0,
        )
        self.graph_power = GpuResourceGraph(
            title="POWER DRAW (% OF TDP LIMIT)",
            subtitle="Board Power Draw Relative to Power Limit (%)",
            history=self.history,
            channels=["power_pct"],
            y_unit="%",
            fixed_max=100.0,
        )
        self.graph_clocks = GpuResourceGraph(
            title="CORE CLOCK SCALING",
            subtitle="Graphics / SM Boost Frequency (% of Max Boost Clock)",
            history=self.history,
            channels=["clock_gfx_pct"],
            y_unit="%",
            fixed_max=100.0,
        )
        self.graph_pcie = GpuResourceGraph(
            title="PCIe BUS BANDWIDTH (TX + RX)",
            subtitle="Real-time PCIe Link Data Throughput (MB/s, Auto-Scaled)",
            history=self.history,
            channels=["pcie_total_mbs"],
            y_unit="M",
            fixed_max=None,
        )

        self.quad_graphs = [
            self.graph_core,
            self.graph_vram,
            self.graph_thermal,
            self.graph_power,
            self.graph_clocks,
            self.graph_pcie,
        ]

        grid.attach(self.graph_core, 0, 0, 1, 1)
        grid.attach(self.graph_vram, 1, 0, 1, 1)
        grid.attach(self.graph_thermal, 0, 1, 1, 1)
        grid.attach(self.graph_power, 1, 1, 1, 1)
        grid.attach(self.graph_clocks, 0, 2, 1, 1)
        grid.attach(self.graph_pcie, 1, 2, 1, 1)
        return grid

    def _build_combined_oscilloscope_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(8)
        vbox.set_margin_end(8)

        self.graph_combined = GpuResourceGraph(
            title="COMBINED MULTI-CHANNEL GPU TELEMETRY OSCILLOSCOPE",
            subtitle="Hover mouse over graph to inspect exact timestamped metrics · Toggle channels in left sidebar",
            history=self.history,
            channels=[
                "gpu_util",
                "vram_pct",
                "mem_ctrl_util",
                "temp_c",
                "power_pct",
                "fan_pct",
                "clock_gfx_pct",
            ],
            y_unit="%",
            fixed_max=100.0,
            min_height=340,
        )
        vbox.pack_start(self.graph_combined, True, True, 0)

        self.vram_bar_combined = VramAllocationBar()
        vbox.pack_start(self.vram_bar_combined, False, False, 0)
        return vbox

    def _build_processes_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(8)
        vbox.set_margin_end(8)

        self.vram_bar_procs = VramAllocationBar()
        vbox.pack_start(self.vram_bar_procs, False, False, 0)

        # Toolbar for filtering & managing GPU processes
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_filter = Gtk.Label(label="Filter GPU Processes:")
        self.entry_proc_filter = Gtk.SearchEntry()
        self.entry_proc_filter.set_placeholder_text("Filter by process name, PID, or command...")
        self.entry_proc_filter.connect("search-changed", lambda *_: self._refresh_process_table())

        btn_copy_cmd = Gtk.Button(label="Copy PID & Command")
        btn_copy_cmd.connect("clicked", self._on_copy_process_clicked)

        btn_kill = Gtk.Button(label="Terminate Process (SIGTERM)")
        btn_kill.set_tooltip_text("Send SIGTERM to selected GPU process")
        btn_kill.connect("clicked", self._on_terminate_process_clicked)

        bar.pack_start(lbl_filter, False, False, 0)
        bar.pack_start(self.entry_proc_filter, True, True, 0)
        bar.pack_end(btn_kill, False, False, 0)
        bar.pack_end(btn_copy_cmd, False, False, 0)
        vbox.pack_start(bar, False, False, 0)

        # TreeView of GPU processes
        # Columns: PID (int), Type (str), Name (str), User (str), VRAM MiB (str), VRAM % (str), Command (str), raw_mib (float)
        self.proc_store = Gtk.ListStore(int, str, str, str, str, str, str, float)
        self.proc_tree = Gtk.TreeView(model=self.proc_store)
        self.proc_tree.set_headers_visible(True)

        cols = [
            ("PID", 0, 75),
            ("Engine", 1, 70),
            ("Process", 2, 165),
            ("User", 3, 95),
            ("VRAM (MiB)", 4, 105),
            ("VRAM (%)", 5, 90),
            ("Command Line", 6, 420),
        ]
        for title, col_idx, min_w in cols:
            renderer = Gtk.CellRendererText()
            if col_idx == 1:
                renderer.set_property("foreground", "#00f0ff")
                renderer.set_property("weight", Pango.Weight.BOLD)
            elif col_idx in (4, 5):
                renderer.set_property("foreground", "#10b981")
                renderer.set_property("weight", Pango.Weight.BOLD)
            col = Gtk.TreeViewColumn(title, renderer, text=col_idx)
            col.set_resizable(True)
            col.set_min_width(min_w)
            col.set_sort_column_id(7 if col_idx in (4, 5) else col_idx)
            self.proc_tree.append_column(col)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.proc_tree)
        vbox.pack_start(scroll, True, True, 0)
        return vbox

    def _build_specs_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(8)
        vbox.set_margin_end(8)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_info = Gtk.Label()
        lbl_info.set_markup(
            "<span foreground='#00f0ff' weight='bold'>GPU HARDWARE, DRIVER &amp; SENSOR DIAGNOSTICS</span>"
        )
        lbl_info.set_xalign(0.0)
        btn_copy = Gtk.Button(label="Copy Full Report")
        btn_copy.connect("clicked", lambda *_: self._copy_gpu_report())
        btn_export_csv = Gtk.Button(label="Export CSV")
        btn_export_csv.connect("clicked", lambda *_: self._export_telemetry("csv"))

        top_bar.pack_start(lbl_info, True, True, 0)
        top_bar.pack_end(btn_export_csv, False, False, 0)
        top_bar.pack_end(btn_copy, False, False, 0)
        vbox.pack_start(top_bar, False, False, 0)

        self.specs_store = Gtk.ListStore(str, str, str)
        tree = Gtk.TreeView(model=self.specs_store)
        for idx, (title, width, color) in enumerate([
            ("Category", 180, "#38bdf8"),
            ("Parameter / Sensor", 260, "#ffffff"),
            ("Current Value", 460, "#00f0ff"),
        ]):
            r = Gtk.CellRendererText()
            r.set_property("foreground", color)
            if idx == 2:
                r.set_property("weight", Pango.Weight.BOLD)
            col = Gtk.TreeViewColumn(title, r, text=idx)
            col.set_resizable(True)
            col.set_min_width(width)
            tree.append_column(col)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(tree)
        vbox.pack_start(scroll, True, True, 0)
        return vbox

    # ------------------------------------------------------------------
    # Status Bar
    # ------------------------------------------------------------------
    def _build_status_bar(self):
        self.statusbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.statusbar.set_name("statusbar")
        self.statusbar.get_style_context().add_class("statusbar")

        self.st_gpu = Gtk.Label(label="GPU 0: GPU")
        self.st_core = Gtk.Label(label="Core: 0%")
        self.st_vram = Gtk.Label(label="VRAM: 0 / 0 MiB (0%)")
        self.st_temp = Gtk.Label(label="Temp: 0°C")
        self.st_power = Gtk.Label(label="Power: 0.0 / 0.0 W")
        self.st_pcie = Gtk.Label(label="PCIe: Gen4 x16")
        self.st_backend = Gtk.Label(label=f"Backend: {self.engine.backend}")
        self.st_zoom = Gtk.Label(label="Retina: 100%")

        for lbl in (
            self.st_gpu,
            self.st_core,
            self.st_vram,
            self.st_temp,
            self.st_power,
            self.st_pcie,
        ):
            lbl.set_xalign(0.0)
            self.statusbar.pack_start(lbl, False, False, 0)

        self.statusbar.pack_end(self.st_zoom, False, False, 0)
        self.statusbar.pack_end(self.st_backend, False, False, 0)
        self.root_vbox.pack_end(self.statusbar, False, False, 0)

    # ------------------------------------------------------------------
    # Keyboard Shortcuts
    # ------------------------------------------------------------------
    def _setup_shortcuts(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        shortcuts = [
            ("<Control>q", lambda *_: self.close()),
            ("<Control>b", lambda *_: self.btn_sidebar.set_active(not self.btn_sidebar.get_active())),
            ("F9", lambda *_: self.btn_sidebar.set_active(not self.btn_sidebar.get_active())),
            ("F10", lambda *_: self.btn_hud.set_active(not self.btn_hud.get_active())),
            ("<Control>r", lambda *_: self._clear_history()),
            ("<Control>plus", lambda *_: self.adjust_zoom(10)),
            ("<Control>equal", lambda *_: self.adjust_zoom(10)),
            ("<Control>minus", lambda *_: self.adjust_zoom(-10)),
            ("<Control>0", lambda *_: self.set_zoom(100)),
        ]
        for key_str, cb in shortcuts:
            key, mod = Gtk.accelerator_parse(key_str)
            if key:
                accel.connect(key, mod, Gtk.AccelFlags.VISIBLE, cb)

    # ------------------------------------------------------------------
    # Telemetry Polling & UI Refresh
    # ------------------------------------------------------------------
    def _restart_timer(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        self._timer_id = GLib.timeout_add(self.poll_interval_ms, self._on_timer_tick)

    def _on_timer_tick(self) -> bool:
        if not self.is_paused:
            self._poll_once()
        return True

    def _poll_once(self):
        snap = self.engine.poll(self.current_gpu_index, include_processes=True)
        self.history.push(snap)
        spec = self.engine.get_device_spec(self.current_gpu_index)
        self._update_ui(snap, spec)

    def _update_ui(self, snap: GpuSnapshot, spec: GpuDeviceSpec):
        # 1. Header PState badge
        self.lbl_pstate.set_text(snap.pstate)

        # 2. Top Radial Gauge Cards
        gpu_stats = self.history.get_channel_stats("gpu_util")
        self.gauge_gpu.update_State(
            pct=snap.gpu_util,
            primary_text=f"{snap.gpu_util:.0f}%",
            secondary_text=f"Mem Bus: {snap.mem_ctrl_util:.0f}%",
            peak_text=f"Peak: {gpu_stats['max']:.0f}% | Avg: {gpu_stats['avg']:.0f}%",
            spark_values=self.history.get_normalized_series("gpu_util", count=48),
        )

        vram_stats = self.history.get_channel_stats("vram_pct")
        self.gauge_vram.update_State(
            pct=snap.vram_pct,
            primary_text=f"{snap.vram_used_mib / 1024.0:.2f} GiB",
            secondary_text=f"{snap.vram_used_mib:.0f} / {snap.vram_total_mib:.0f} MiB",
            peak_text=f"Peak: {vram_stats['max']:.1f}% ({len(snap.processes)} procs)",
            spark_values=self.history.get_normalized_series("vram_pct", count=48),
        )

        temp_stats = self.history.get_channel_stats("temp_c")
        self.gauge_temp.update_State(
            pct=snap.temp_c,
            primary_text=f"{snap.temp_c:.0f}°C",
            secondary_text=f"Slowdown: {spec.temp_slowdown_c}°C",
            peak_text=f"Peak: {temp_stats['max']:.0f}°C | Min: {temp_stats['min']:.0f}°C",
            spark_values=self.history.get_normalized_series("temp_c", count=48),
        )

        pwr_stats = self.history.get_channel_stats("power_pct")
        self.gauge_pwr.update_State(
            pct=snap.power_pct,
            primary_text=f"{snap.power_draw_w:.1f} W",
            secondary_text=f"Limit: {snap.power_limit_w:.0f} W ({snap.power_pct:.0f}%)",
            peak_text=f"Peak: {(pwr_stats['max'] / 100.0) * snap.power_limit_w:.1f} W",
            spark_values=self.history.get_normalized_series("power_pct", count=48),
        )

        fan_stats = self.history.get_channel_stats("fan_pct")
        self.gauge_fan.update_State(
            pct=snap.fan_pct,
            primary_text=f"{snap.fan_pct:.0f}%",
            secondary_text="Zero-RPM Idle" if snap.fan_pct == 0 else "Active Cooling",
            peak_text=f"Peak Fan: {fan_stats['max']:.0f}%",
            spark_values=self.history.get_normalized_series("fan_pct", count=48),
        )

        self.gauge_clk.update_State(
            pct=snap.clock_gfx_pct,
            primary_text=f"{snap.clock_gfx_mhz} MHz",
            secondary_text=f"Mem: {snap.clock_mem_mhz} MHz",
            peak_text=f"Max Boost: {snap.clock_max_gfx_mhz} MHz",
            spark_values=self.history.get_normalized_series("clock_gfx_pct", count=48),
        )

        # 3. Redraw visible Cairo graphs
        sec_rate = self.poll_interval_ms / 1000.0
        for g in self.quad_graphs + [self.graph_combined]:
            g.poll_interval_sec = sec_rate
            g.queue_draw()

        self.vram_bar_combined.update_snapshot(snap)
        self.vram_bar_procs.update_snapshot(snap)

        # 4. Sidebar hardware summary & channel readouts
        self.lbl_hw_summary.set_markup(
            f"<span font_family='monospace' size='small'>"
            f"<b>Model:</b>  {GLib.markup_escape_text(spec.name)}\n"
            f"<b>Driver:</b> {spec.driver_version} (CUDA {spec.cuda_version})\n"
            f"<b>VBIOS:</b>  {spec.vbios_version}\n"
            f"<b>Bus ID:</b> {spec.bus_id} (Gen{snap.pcie_gen} x{snap.pcie_width})\n"
            f"<b>VRAM:</b>   {snap.vram_total_mib:.0f} MiB ({snap.vram_total_mib / 1024.0:.0f} GiB)\n"
            f"<b>TDP:</b>    {snap.power_limit_w:.0f} W | P-State: <span foreground='#00f0ff'><b>{snap.pstate}</b></span>"
            f"</span>"
        )

        for key, lbl in self.channel_stat_labels.items():
            st = self.history.get_channel_stats(key)
            meta = METRIC_CHANNELS[key]
            fmt = str(meta["format"])
            cur_s = fmt.format(st["current"])
            max_s = fmt.format(st["max"])
            lbl.set_markup(
                f"<span font_family='monospace' size='small'><b>{cur_s}</b> <span foreground='#64748b'>(pk {max_s})</span></span>"
            )

        # 5. Refresh process table & specs table
        self._last_snapshot = snap
        self._refresh_process_table()
        self._refresh_specs_table(snap, spec)

        # 6. Status bar
        self.st_gpu.set_markup(
            f"<span foreground='#00f0ff' weight='bold'>GPU {snap.gpu_index}:</span> {GLib.markup_escape_text(spec.name)} [{snap.pstate}]"
        )
        self.st_core.set_text(f"Core: {snap.gpu_util:.0f}% (MemBus {snap.mem_ctrl_util:.0f}%)")
        self.st_vram.set_text(
            f"VRAM: {snap.vram_used_mib:.0f} / {snap.vram_total_mib:.0f} MiB ({snap.vram_pct:.1f}%)"
        )
        self.st_temp.set_text(f"Temp: {snap.temp_c:.0f}°C (Fan {snap.fan_pct:.0f}%)")
        self.st_power.set_text(f"Power: {snap.power_draw_w:.1f} / {snap.power_limit_w:.0f} W")
        self.st_pcie.set_text(
            f"PCIe: {snap.pcie_tx_mbs + snap.pcie_rx_mbs:.1f} MB/s (Gen{snap.pcie_gen} x{snap.pcie_width})"
        )

    def _refresh_process_table(self):
        snap: Optional[GpuSnapshot] = getattr(self, "_last_snapshot", None)
        if not snap:
            return
        query = self.entry_proc_filter.get_text().strip().lower()

        # Preserve currently selected PID
        selected_pid = self._get_selected_pid()

        self.proc_store.clear()
        restore_iter = None
        for p in snap.processes:
            if query:
                hay = f"{p.pid} {p.name} {p.user} {p.cmdline} {p.proc_type}".lower()
                if query not in hay:
                    continue
            it = self.proc_store.append([
                p.pid,
                p.proc_type,
                p.name,
                p.user,
                f"{p.vram_mib:.1f} MiB",
                f"{p.vram_pct:.2f}%",
                p.cmdline,
                p.vram_mib,
            ])
            if selected_pid is not None and p.pid == selected_pid:
                restore_iter = it

        if restore_iter is not None:
            self.proc_tree.get_selection().select_iter(restore_iter)

    def _refresh_specs_table(self, snap: GpuSnapshot, spec: GpuDeviceSpec):
        self.specs_store.clear()
        rows = [
            ("Device Identity", "GPU Name", spec.name),
            ("Device Identity", "GPU UUID", spec.uuid),
            ("Device Identity", "PCI Bus ID", spec.bus_id),
            ("Device Identity", "VBIOS Version", spec.vbios_version),
            ("Driver & Compute", "Graphics Driver Version", spec.driver_version),
            ("Driver & Compute", "CUDA Version", spec.cuda_version),
            ("Driver & Compute", "Telemetry Backend", spec.backend),
            ("Driver & Compute", "Performance State (P-State)", snap.pstate),
            ("Utilization", "GPU Core (SM) Utilization", f"{snap.gpu_util:.1f}%"),
            ("Utilization", "Memory Controller Utilization", f"{snap.mem_ctrl_util:.1f}%"),
            ("Utilization", "Video Encoder (NVENC)", f"{snap.enc_util:.1f}%"),
            ("Utilization", "Video Decoder (NVDEC)", f"{snap.dec_util:.1f}%"),
            ("Video Memory", "VRAM Used", f"{snap.vram_used_mib:.1f} MiB ({snap.vram_used_mib / 1024.0:.2f} GiB · {snap.vram_pct:.2f}%)"),
            ("Video Memory", "VRAM Free", f"{snap.vram_free_mib:.1f} MiB ({snap.vram_free_mib / 1024.0:.2f} GiB)"),
            ("Video Memory", "VRAM Total", f"{snap.vram_total_mib:.1f} MiB ({snap.vram_total_mib / 1024.0:.2f} GiB)"),
            ("Clocks", "Graphics / Shader Clock", f"{snap.clock_gfx_mhz} MHz (Max Boost: {spec.clock_max_gfx_mhz} MHz)"),
            ("Clocks", "Streaming Multiprocessor (SM) Clock", f"{snap.clock_sm_mhz} MHz (Max: {spec.clock_max_sm_mhz} MHz)"),
            ("Clocks", "Memory Clock", f"{snap.clock_mem_mhz} MHz (Max: {spec.clock_max_mem_mhz} MHz)"),
            ("Thermal & Cooling", "GPU Core Temperature", f"{snap.temp_c:.1f} °C"),
            ("Thermal & Cooling", "Thermal Slowdown / Shutdown", f"{spec.temp_slowdown_c} °C / {spec.temp_shutdown_c} °C"),
            ("Thermal & Cooling", "Fan Speed", f"{snap.fan_pct:.1f}%"),
            ("Power", "Current Board Power Draw", f"{snap.power_draw_w:.2f} W ({snap.power_pct:.1f}% of limit)"),
            ("Power", "Configured / Max Power Limit", f"{snap.power_limit_w:.1f} W / {spec.power_max_limit_w:.1f} W"),
            ("PCIe Interface", "Active PCIe Link", f"Gen {snap.pcie_gen} x{snap.pcie_width} (Max: Gen {spec.pcie_max_gen} x{spec.pcie_max_width})"),
            ("PCIe Interface", "PCIe TX / RX Bandwidth", f"TX: {snap.pcie_tx_mbs:.2f} MB/s  |  RX: {snap.pcie_rx_mbs:.2f} MB/s"),
            ("Active Workloads", "Active GPU Processes", f"{len(snap.processes)} processes ({sum(1 for p in snap.processes if 'C' in p.proc_type)} Compute)"),
        ]
        for cat, param, val in rows:
            self.specs_store.append([cat, param, val])

    # ------------------------------------------------------------------
    # Cinnamon Panel Applet & Desktop Desklet Integration Handlers
    # ------------------------------------------------------------------
    def _refresh_applet_button_style(self):
        ctx = self.btn_applet_mgr.get_style_context()
        applet_on = self.cinnamon_mgr.is_applet_enabled()
        desklet_on = self.cinnamon_mgr.is_desklet_enabled()
        if applet_on or desklet_on:
            ctx.add_class("applet-active-btn")
            self.btn_applet_mgr.set_label("Applet: Active")
        else:
            ctx.remove_class("applet-active-btn")
            self.btn_applet_mgr.set_label("Install Applet")

    def _on_panel_applet_switch(self, switch: Gtk.Switch, _gparam):
        self.cinnamon_mgr.set_applet_enabled(switch.get_active())
        self._refresh_applet_button_style()

    def _on_desklet_switch(self, switch: Gtk.Switch, _gparam):
        self.cinnamon_mgr.set_desklet_enabled(switch.get_active())
        self._refresh_applet_button_style()

    def _on_desk_size_preset_changed(self, combo: Gtk.ComboBoxText):
        idx = combo.get_active()
        if 0 <= idx < len(self._desk_size_presets):
            _, w, h = self._desk_size_presets[idx]
            self.cinnamon_mgr.set_desklet_dimensions(w, h)

    def _on_sync_applets_clicked(self, _btn):
        self.cinnamon_mgr.install_files()
        self.cinnamon_mgr.pin_to_cinnamon_panel_and_favorites()
        self._refresh_applet_button_style()

    def _show_cinnamon_applet_dialog(self):
        dlg = Gtk.Dialog(
            title="GPUpanel — Cinnamon Desktop & Panel Applet Manager",
            transient_for=self,
            flags=0,
        )
        dlg.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dlg.set_default_size(520, 320)

        area = dlg.get_content_area()
        area.set_spacing(12)
        area.set_margin_top(14)
        area.set_margin_bottom(14)
        area.set_margin_start(16)
        area.set_margin_end(16)

        title = Gtk.Label()
        title.set_markup(
            "<span size='large' weight='bold' foreground='#00f0ff'>"
            "Linux Mint Cinnamon Applet &amp; Desktop Graph Integration"
            "</span>"
        )
        title.set_xalign(0.0)
        area.pack_start(title, False, False, 0)

        desc = Gtk.Label(
            label=(
                "GPUpanel includes both a live Cinnamon Panel Bar Applet (mini Cairo graph + telemetry popup "
                "in your system tray/panel) and a Cinnamon Desktop Graph Desklet (live multi-channel resource "
                "graph widget directly on your desktop wallpaper)."
            )
        )
        desc.set_line_wrap(True)
        desc.set_xalign(0.0)
        area.pack_start(desc, False, False, 0)

        # Panel Applet Card
        card1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card1.get_style_context().add_class("neon-card")
        v1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        l1 = Gtk.Label()
        l1.set_markup("<b>1. Cinnamon Panel Bar Applet (<tt>gpupanel@cinnamon</tt>)</b>")
        l1.set_xalign(0.0)
        s1 = Gtk.Label(label="Displays live Cairo GPU sparkline + GPU% · VRAM · Temp°C directly on your panel.")
        s1.set_xalign(0.0)
        v1.pack_start(l1, False, False, 0)
        v1.pack_start(s1, False, False, 0)

        sw1 = Gtk.Switch()
        sw1.set_valign(Gtk.Align.CENTER)
        sw1.set_active(self.cinnamon_mgr.is_applet_enabled())

        def _toggle_p(sw, _pspec):
            self.cinnamon_mgr.set_applet_enabled(sw.get_active())
            self.sw_panel_applet.set_active(sw.get_active())
            self._refresh_applet_button_style()

        sw1.connect("notify::active", _toggle_p)
        card1.pack_start(v1, True, True, 0)
        card1.pack_end(sw1, False, False, 0)
        area.pack_start(card1, False, False, 0)

        # Desktop Desklet Card
        card2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card2.get_style_context().add_class("neon-card")
        v2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        l2 = Gtk.Label()
        l2.set_markup("<b>2. Cinnamon Desktop Graph Desklet (<tt>gpupanel@cinnamon</tt>)</b>")
        l2.set_xalign(0.0)
        s2 = Gtk.Label(label="Renders a PythonPanel Dark Neon GPU oscilloscope widget directly on your desktop.")
        s2.set_xalign(0.0)
        v2.pack_start(l2, False, False, 0)
        v2.pack_start(s2, False, False, 0)

        sw2 = Gtk.Switch()
        sw2.set_valign(Gtk.Align.CENTER)
        sw2.set_active(self.cinnamon_mgr.is_desklet_enabled())

        def _toggle_d(sw, _pspec):
            self.cinnamon_mgr.set_desklet_enabled(sw.get_active())
            self.sw_desklet.set_active(sw.get_active())
            self._refresh_applet_button_style()

        sw2.connect("notify::active", _toggle_d)
        card2.pack_start(v2, True, True, 0)
        card2.pack_end(sw2, False, False, 0)
        area.pack_start(card2, False, False, 0)

        # Pin to grouped-window-list button
        btn_pin = Gtk.Button(label="Install / Update Applet Files & Pin GPUpanel Launcher to Panel")
        btn_pin.connect("clicked", self._on_sync_applets_clicked)
        area.pack_start(btn_pin, False, False, 0)

        dlg.show_all()
        dlg.run()
        dlg.destroy()

    # ------------------------------------------------------------------
    # Mini Floating HUD Mode (F10)
    # ------------------------------------------------------------------
    def toggle_hud_mode(self, enable: bool):
        self.is_hud_mode = bool(enable)
        if self.btn_hud.get_active() != self.is_hud_mode:
            self.btn_hud.set_active(self.is_hud_mode)

        if self.is_hud_mode:
            self.sidebar_box.set_visible(False)
            self.gauge_grid.set_visible(False)
            self.statusbar.set_visible(False)
            self.notebook.set_current_page(1)  # Combined oscilloscope
            self.notebook.set_show_tabs(False)
            self.set_keep_above(True)
            self.resize(520, 290)
        else:
            self.sidebar_box.set_visible(self.btn_sidebar.get_active())
            self.gauge_grid.set_visible(True)
            self.statusbar.set_visible(True)
            self.notebook.set_show_tabs(True)
            self.set_keep_above(False)
            self.resize(1220, 780)

    # ------------------------------------------------------------------
    # Event Handlers & Actions
    # ------------------------------------------------------------------
    def _on_sidebar_toggled(self, btn: Gtk.ToggleButton):
        if hasattr(self, "sidebar_box"):
            self.sidebar_box.set_visible(btn.get_active())

    def _on_gpu_changed(self, combo: Gtk.ComboBoxText):
        idx = combo.get_active()
        if idx >= 0 and idx != self.current_gpu_index:
            self.current_gpu_index = idx
            self.history.clear()
            self._poll_once()

    def _on_rate_changed(self, combo: Gtk.ComboBoxText):
        rates = [250, 500, 1000, 2000]
        idx = combo.get_active()
        if 0 <= idx < len(rates):
            self.poll_interval_ms = rates[idx]
            self._restart_timer()

    def _on_pause_toggled(self, btn: Gtk.ToggleButton):
        self.is_paused = btn.get_active()
        btn.set_label("Resume" if self.is_paused else "Pause")

    def _on_channel_check_toggled(self, chk: Gtk.CheckButton, key: str):
        self.graph_combined.set_channel_enabled(key, chk.get_active())

    def _on_grid_toggled(self, chk: Gtk.CheckButton):
        for g in self.quad_graphs + [self.graph_combined]:
            g.show_grid = chk.get_active()
            g.queue_draw()

    def _on_fill_toggled(self, chk: Gtk.CheckButton):
        for g in self.quad_graphs + [self.graph_combined]:
            g.show_area_fill = chk.get_active()
            g.queue_draw()

    def _clear_history(self):
        self.history.clear()
        self._poll_once()

    def adjust_zoom(self, delta: int):
        self.set_zoom(self.zoom_pct + delta)

    def set_zoom(self, pct: int):
        self.zoom_pct = max(70, min(200, int(pct)))
        scale = self.zoom_pct / 100.0
        self.btn_z_reset.set_label(f"{self.zoom_pct}%")
        self.st_zoom.set_text(f"Retina: {self.zoom_pct}%")
        for g in self.gauges:
            g.set_zoom_scale(scale)
        for gr in self.quad_graphs + [self.graph_combined]:
            gr.set_zoom_scale(scale)

    def _on_scroll_zoom(self, _widget, event: Gdk.EventScroll) -> bool:
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.direction == Gdk.ScrollDirection.UP:
                self.adjust_zoom(10)
                return True
            if event.direction == Gdk.ScrollDirection.DOWN:
                self.adjust_zoom(-10)
                return True
        return False

    def _get_selected_pid(self) -> Optional[int]:
        sel = self.proc_tree.get_selection()
        model, it = sel.get_selected()
        if it is not None:
            return int(model.get_value(it, 0))
        return None

    def _on_copy_process_clicked(self, _btn):
        sel = self.proc_tree.get_selection()
        model, it = sel.get_selected()
        if it is not None:
            pid = model.get_value(it, 0)
            name = model.get_value(it, 2)
            vram = model.get_value(it, 4)
            cmd = model.get_value(it, 6)
            txt = f"PID {pid} ({name}) | VRAM: {vram} | Command: {cmd}"
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(txt, -1)

    def _on_terminate_process_clicked(self, _btn):
        pid = self._get_selected_pid()
        if pid is None:
            return
        if pid in (1, os.getpid()):
            return
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Terminate GPU Process PID {pid}?",
        )
        dlg.format_secondary_text(
            f"This will send SIGTERM to process {pid}. System display servers (Xorg/cinnamon) should not be terminated."
        )
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                os.kill(pid, signal.SIGTERM)
                GLib.timeout_add(300, lambda: (self._poll_once(), False)[1])
            except Exception as e:
                err = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text=f"Could not terminate PID {pid}: {e}",
                )
                err.run()
                err.destroy()

    def _export_telemetry(self, fmt: str):
        dlg = Gtk.FileChooserDialog(
            title=f"Export GPU Telemetry History ({fmt.upper()})",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dlg.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.ACCEPT,
        )
        dlg.set_do_overwrite_confirmation(True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dlg.set_current_name(f"gpupanel_telemetry_{ts}.{fmt}")
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            path = dlg.get_filename()
            try:
                if fmt == "csv":
                    self.history.export_csv(path)
                else:
                    self.history.export_json(path)
            except Exception:
                pass
        dlg.destroy()

    def _copy_gpu_report(self):
        snap = self.history.latest()
        spec = self.engine.get_device_spec(self.current_gpu_index)
        if not snap:
            return
        report = (
            f"GPUpanel Telemetry Summary — {spec.name}\n"
            f"Driver: {spec.driver_version} | CUDA: {spec.cuda_version} | Bus: {spec.bus_id} | P-State: {snap.pstate}\n"
            f"Core Load: {snap.gpu_util:.1f}% | Mem Bus: {snap.mem_ctrl_util:.1f}%\n"
            f"VRAM: {snap.vram_used_mib:.1f} / {snap.vram_total_mib:.1f} MiB ({snap.vram_pct:.1f}%)\n"
            f"Thermal: {snap.temp_c:.1f}°C | Fan: {snap.fan_pct:.1f}%\n"
            f"Power: {snap.power_draw_w:.2f} / {snap.power_limit_w:.1f} W ({snap.power_pct:.1f}%)\n"
            f"Clocks: {snap.clock_gfx_mhz} MHz Core / {snap.clock_mem_mhz} MHz Mem\n"
            f"PCIe Bandwidth: TX {snap.pcie_tx_mbs:.2f} MB/s | RX {snap.pcie_rx_mbs:.2f} MB/s\n"
            f"Active GPU Processes: {len(snap.processes)}"
        )
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(report, -1)

    def _show_retina_info_dialog(self):
        screen = self.get_screen()
        display = screen.get_display() if screen else None
        scale = self.get_scale_factor()
        mon_info = "Unknown"
        if display and display.get_n_monitors() > 0:
            mon = display.get_monitor(0)
            geom = mon.get_geometry()
            mon_info = f"{geom.width}x{geom.height} @ {scale}x HiDPI scale"

        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="GPUpanel Retina Vision & Cairo Subpixel Diagnostics",
        )
        dlg.format_secondary_text(
            f"Monitor Geometry: {mon_info}\n"
            f"Cairo Renderer: Subpixel Anti-Aliased Vector Oscilloscope (ANTIALIAS_BEST)\n"
            f"Current Retina Zoom: {self.zoom_pct}%\n"
            f"Telemetry Backend: {self.engine.backend} (Poll Rate: {self.poll_interval_ms} ms)"
        )
        dlg.run()
        dlg.destroy()

    def _show_about_dialog(self):
        about = Gtk.AboutDialog(transient_for=self, modal=True)
        about.set_program_name(self.APP_NAME)
        about.set_version(self.APP_VERSION)
        about.set_comments(
            "Real-time GPU Resource Graph Workstation, Cinnamon Panel Applet, "
            "and Desktop Graph Desklet in the PythonPanel Dark Neon aesthetic."
        )
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpupanel.svg")
        if os.path.exists(icon_path):
            try:
                about.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 96, 96, True))
            except Exception:
                pass
        about.run()
        about.destroy()

    def _on_delete_event(self, *_args):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        self.engine.shutdown()
        return False


class GpuPanelApplication(Gtk.Application):
    """GTK Application wrapper for GPUpanel."""

    def __init__(self, start_hud: bool = False):
        super().__init__(
            application_id="org.cinnamon.gpupanel",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        GLib.set_prgname("gpupanel")
        GLib.set_application_name("GPUpanel")
        self.start_hud = start_hud

    def do_activate(self):
        win = GpuPanelWindow(self, start_hud=self.start_hud)
        win.present()


def main():
    start_hud = "--hud" in sys.argv
    app = GpuPanelApplication(start_hud=start_hud)
    sys.exit(app.run([sys.argv[0]]))


if __name__ == "__main__":
    main()
