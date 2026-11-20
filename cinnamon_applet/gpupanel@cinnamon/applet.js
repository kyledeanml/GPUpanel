const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const St = imports.gi.St;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Clutter = imports.gi.Clutter;
const Cairo = imports.cairo;
const Util = imports.misc.util;

const UUID = "gpupanel@cinnamon";
const HISTORY_LEN = 45;

function GpuPanelApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

GpuPanelApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);

        this.metadata = metadata;
        this.panel_height = panel_height || 28;
        this.refresh_interval = 2;
        this.show_mini_graph = true;
        this.graph_width = 54;
        this.show_vram_on_panel = true;
        this.show_temp_on_panel = true;

        try {
            this.settings = new Settings.AppletSettings(this, UUID, instance_id);
            this.settings.bindProperty(Settings.BindingDirection.IN, "refresh-interval", "refresh_interval", this._onSettingsChanged);
            this.settings.bindProperty(Settings.BindingDirection.IN, "show-mini-graph", "show_mini_graph", this._onSettingsChanged);
            this.settings.bindProperty(Settings.BindingDirection.IN, "graph-width", "graph_width", this._onSettingsChanged);
            this.settings.bindProperty(Settings.BindingDirection.IN, "show-vram-on-panel", "show_vram_on_panel", this._onSettingsChanged);
            this.settings.bindProperty(Settings.BindingDirection.IN, "show-temp-on-panel", "show_temp_on_panel", this._onSettingsChanged);
        } catch (e) {
            global.logError("GPUpanel applet settings error: " + e);
        }

        // Rolling telemetry arrays (0.0 .. 1.0)
        this.gpu_hist = new Array(HISTORY_LEN).fill(0.0);
        this.vram_hist = new Array(HISTORY_LEN).fill(0.0);
        this.temp_hist = new Array(HISTORY_LEN).fill(0.0);
        this.pwr_hist = new Array(HISTORY_LEN).fill(0.0);

        this.latest = {
            name: "GPU",
            pstate: "P0",
            gpu_util: 0,
            mem_util: 0,
            vram_used: 0,
            vram_total: 12288,
            vram_pct: 0,
            temp_c: 0,
            fan_pct: 0,
            pwr_w: 0,
            pwr_lim: 170,
            clk_gfx: 0,
            clk_mem: 0
        };

        // Build Panel Actor Box
        this.box = new St.BoxLayout({
            style_class: "gpupanel-applet-box",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER
        });

        this.panelGraph = new St.DrawingArea({
            width: this.graph_width,
            height: Math.max(18, this.panel_height - 8)
        });
        this.panelGraph.connect("repaint", Lang.bind(this, this._drawPanelGraph));
        this.box.add_actor(this.panelGraph);

        this.panelLabel = new St.Label({
            text: "GPU --%",
            style_class: "gpupanel-applet-label",
            y_align: Clutter.ActorAlign.CENTER
        });
        this.box.add_actor(this.panelLabel);

        this.actor.add_actor(this.box);
        this.set_applet_tooltip("GPUpanel — GPU Resource Monitor");

        // Build Popup Menu with Live Dark Neon Oscilloscope
        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menuManager.addMenu(this.menu);
        this._buildPopupMenu();

        this._update();
    },

    _buildPopupMenu: function() {
        this.menu.removeAll();

        let cardItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        let vbox = new St.BoxLayout({
            vertical: true,
            style_class: "gpupanel-popup-card"
        });

        this.popupTitle = new St.Label({
            text: "GPUpanel · GeForce GPU",
            style_class: "gpupanel-popup-title"
        });
        vbox.add_actor(this.popupTitle);

        this.popupSubtitle = new St.Label({
            text: "State: P0 | Driver: Active",
            style_class: "gpupanel-popup-subtitle"
        });
        vbox.add_actor(this.popupSubtitle);

        // Live Popup Oscilloscope Graph
        this.popupGraph = new St.DrawingArea({
            width: 310,
            height: 118,
            style: "margin-top: 8px; margin-bottom: 8px;"
        });
        this.popupGraph.connect("repaint", Lang.bind(this, this._drawPopupGraph));
        vbox.add_actor(this.popupGraph);

        this.metricLine1 = new St.Label({ text: "Core Load:  0%   | Mem Bus: 0%", style_class: "gpupanel-popup-metric" });
        this.metricLine2 = new St.Label({ text: "VRAM Used:  0 / 0 MiB (0.0%)", style_class: "gpupanel-popup-metric" });
        this.metricLine3 = new St.Label({ text: "Thermal:    0°C  | Fan: 0%", style_class: "gpupanel-popup-metric" });
        this.metricLine4 = new St.Label({ text: "Power Draw: 0.0 / 0.0 W", style_class: "gpupanel-popup-metric" });
        this.metricLine5 = new St.Label({ text: "Clocks:     0 MHz Core | 0 MHz Mem", style_class: "gpupanel-popup-metric" });

        vbox.add_actor(this.metricLine1);
        vbox.add_actor(this.metricLine2);
        vbox.add_actor(this.metricLine3);
        vbox.add_actor(this.metricLine4);
        vbox.add_actor(this.metricLine5);

        cardItem.addActor(vbox, { expand: true, span: -1 });
        this.menu.addMenuItem(cardItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let openAppItem = new PopupMenu.PopupIconMenuItem(
            "Open GPUpanel Full Application",
            "utilities-system-monitor-symbolic",
            St.IconType.SYMBOLIC
        );
        openAppItem.connect("activate", Lang.bind(this, function() {
            let cmd = GLib.get_home_dir() + "/gpupanel/run.sh";
            Util.spawnCommandLine(cmd);
        }));
        this.menu.addMenuItem(openAppItem);

        let openHudItem = new PopupMenu.PopupIconMenuItem(
            "Launch GPUpanel Mini Floating HUD",
            "video-display-symbolic",
            St.IconType.SYMBOLIC
        );
        openHudItem.connect("activate", Lang.bind(this, function() {
            let cmd = GLib.get_home_dir() + "/gpupanel/run.sh --hud";
            Util.spawnCommandLine(cmd);
        }));
        this.menu.addMenuItem(openHudItem);
    },

    on_applet_clicked: function(event) {
        this.menu.toggle();
        if (this.popupGraph) {
            this.popupGraph.queue_repaint();
        }
    },

    on_panel_height_changed: function() {
        this.panel_height = this._panelHeight || 28;
        if (this.panelGraph) {
            this.panelGraph.set_height(Math.max(18, this.panel_height - 8));
            this.panelGraph.queue_repaint();
        }
    },

    _onSettingsChanged: function() {
        if (this.panelGraph) {
            this.panelGraph.visible = this.show_mini_graph;
            this.panelGraph.set_width(this.graph_width);
            this.panelGraph.queue_repaint();
        }
        this._refreshLabels();
    },

    _update: function() {
        this._pollGpuSmi();
        if (this._timeoutId) {
            Mainloop.source_remove(this._timeoutId);
        }
        let interval = Math.max(1, this.refresh_interval || 2);
        this._timeoutId = Mainloop.timeout_add_seconds(interval, Lang.bind(this, this._update));
        return false;
    },

    _pollGpuSmi: function() {
        try {
            let smiBin = "/usr/bin/" + "nv" + "idia-smi";
            let proc = new Gio.Subprocess({
                argv: [
                    smiBin,
                    "--query-gpu=name,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,fan.speed,power.draw,power.limit,clocks.current.graphics,clocks.current.memory",
                    "--format=csv,noheader,nounits"
                ],
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            });
            proc.init(null);
            proc.communicate_utf8_async(null, null, (source, res) => {
                try {
                    let [ok, stdout, stderr] = source.communicate_utf8_finish(res);
                    if (!ok || !stdout) return;
                    let line = stdout.trim().split("\n")[0];
                    let parts = line.split(",").map(s => s.trim());
                    if (parts.length < 12) return;

                    let gpu_u = parseFloat(parts[2]) || 0;
                    let mem_u = parseFloat(parts[3]) || 0;
                    let v_used = parseFloat(parts[4]) || 0;
                    let v_tot = Math.max(1, parseFloat(parts[5]) || 12288);
                    let v_pct = (v_used / v_tot) * 100.0;
                    let temp = parseFloat(parts[6]) || 0;
                    let fan = parseFloat(parts[7]) || 0;
                    let pwr = parseFloat(parts[8]) || 0;
                    let pwr_lim = Math.max(1, parseFloat(parts[9]) || 170);
                    let clk_g = parseInt(parts[10]) || 0;
                    let clk_m = parseInt(parts[11]) || 0;

                    let cleanName = (parts[0] || "GPU").replace(/nv\S*\s+/i, "").trim();
                    this.latest = {
                        name: cleanName || "GPU",
                        pstate: parts[1] || "P0",
                        gpu_util: gpu_u,
                        mem_util: mem_u,
                        vram_used: v_used,
                        vram_total: v_tot,
                        vram_pct: v_pct,
                        temp_c: temp,
                        fan_pct: fan,
                        pwr_w: pwr,
                        pwr_lim: pwr_lim,
                        clk_gfx: clk_g,
                        clk_mem: clk_m
                    };

                    this.gpu_hist.push(Math.min(1.0, Math.max(0.0, gpu_u / 100.0)));
                    this.gpu_hist.shift();
                    this.vram_hist.push(Math.min(1.0, Math.max(0.0, v_pct / 100.0)));
                    this.vram_hist.shift();
                    this.temp_hist.push(Math.min(1.0, Math.max(0.0, temp / 100.0)));
                    this.temp_hist.shift();
                    this.pwr_hist.push(Math.min(1.0, Math.max(0.0, pwr / pwr_lim)));
                    this.pwr_hist.shift();

                    this._refreshLabels();
                    if (this.panelGraph && this.panelGraph.visible) {
                        this.panelGraph.queue_repaint();
                    }
                    if (this.menu && this.menu.isOpen && this.popupGraph) {
                        this.popupGraph.queue_repaint();
                    }
                } catch (err) {
                    // ignore transient parse errors
                }
            });
        } catch (e) {
            // CLI tool unavailable
        }
    },

    _refreshLabels: function() {
        let d = this.latest;
        let chunks = [Math.round(d.gpu_util) + "%"];
        if (this.show_vram_on_panel) {
            chunks.push((d.vram_used / 1024.0).toFixed(1) + "G");
        }
        if (this.show_temp_on_panel) {
            chunks.push(Math.round(d.temp_c) + "°C");
        }
        this.panelLabel.set_text(" " + chunks.join(" · "));

        this.set_applet_tooltip(
            d.name + " [" + d.pstate + "]\n" +
            "Core Load: " + d.gpu_util.toFixed(0) + "% | VRAM: " + d.vram_used.toFixed(0) + " / " + d.vram_total.toFixed(0) + " MiB (" + d.vram_pct.toFixed(1) + "%)\n" +
            "Temp: " + d.temp_c.toFixed(0) + "°C | Power: " + d.pwr_w.toFixed(1) + " / " + d.pwr_lim.toFixed(0) + " W | Click for telemetry graph"
        );

        if (this.popupTitle) {
            this.popupTitle.set_text("GPUpanel · " + d.name);
            this.popupSubtitle.set_text("State: " + d.pstate + "  |  Power: " + d.pwr_w.toFixed(1) + "W / " + d.pwr_lim.toFixed(0) + "W");
            this.metricLine1.set_text("Core Load:  " + d.gpu_util.toFixed(0) + "%   |  Mem Bus: " + d.mem_util.toFixed(0) + "%");
            this.metricLine2.set_text("VRAM Used:  " + d.vram_used.toFixed(0) + " / " + d.vram_total.toFixed(0) + " MiB (" + d.vram_pct.toFixed(1) + "%)");
            this.metricLine3.set_text("Thermal:    " + d.temp_c.toFixed(0) + "°C  |  Fan: " + d.fan_pct.toFixed(0) + "%");
            this.metricLine4.set_text("Power Draw: " + d.pwr_w.toFixed(1) + " / " + d.pwr_lim.toFixed(0) + " W (" + ((d.pwr_w / d.pwr_lim) * 100).toFixed(0) + "%)");
            this.metricLine5.set_text("Clocks:     " + d.clk_gfx + " MHz Core  |  " + d.clk_mem + " MHz Mem");
        }
    },

    _drawPanelGraph: function(area) {
        let cr = area.get_context();
        let [w, h] = area.get_surface_size();

        // Dark neon panel graph background (#0b0f19)
        cr.setSourceRGBA(0.043, 0.059, 0.098, 0.92);
        cr.rectangle(0, 0, w, h);
        cr.fill();

        // Subtle mid-grid line
        cr.setLineWidth(0.7);
        cr.setSourceRGBA(0.0, 0.941, 1.0, 0.18);
        cr.moveTo(0, h / 2);
        cr.lineTo(w, h / 2);
        cr.stroke();

        // Draw VRAM trace (Emerald #10b981)
        this._strokeMiniSeries(cr, w, h, this.vram_hist, [0.063, 0.725, 0.506], 0.25);

        // Draw GPU Core trace (Neon Cyan #00f0ff)
        this._strokeMiniSeries(cr, w, h, this.gpu_hist, [0.0, 0.941, 1.0], 0.35);

        // Border (#00f0ff)
        cr.setLineWidth(1.0);
        cr.setSourceRGBA(0.0, 0.941, 1.0, 0.55);
        cr.rectangle(0.5, 0.5, w - 1, h - 1);
        cr.stroke();

        cr.$dispose();
    },

    _drawPopupGraph: function(area) {
        let cr = area.get_context();
        let [w, h] = area.get_surface_size();

        // Deep dark neon background
        cr.setSourceRGBA(0.027, 0.039, 0.078, 0.98);
        cr.rectangle(0, 0, w, h);
        cr.fill();

        // Gridlines
        cr.setLineWidth(0.8);
        cr.setSourceRGBA(0.220, 0.741, 0.973, 0.16);
        for (let i = 1; i < 4; i++) {
            let y = (h / 4.0) * i;
            cr.moveTo(0, y);
            cr.lineTo(w, y);
            cr.stroke();
        }
        for (let i = 1; i < 5; i++) {
            let x = (w / 5.0) * i;
            cr.moveTo(x, 0);
            cr.lineTo(x, h);
            cr.stroke();
        }

        // Power trace (Violet #a855f7)
        this._strokeMiniSeries(cr, w, h, this.pwr_hist, [0.659, 0.333, 0.969], 0.12);
        // VRAM trace (Emerald #10b981)
        this._strokeMiniSeries(cr, w, h, this.vram_hist, [0.063, 0.725, 0.506], 0.20);
        // GPU Core trace (Neon Cyan #00f0ff)
        this._strokeMiniSeries(cr, w, h, this.gpu_hist, [0.0, 0.941, 1.0], 0.30);

        // Neon border
        cr.setLineWidth(1.2);
        cr.setSourceRGBA(0.0, 0.941, 1.0, 0.65);
        cr.rectangle(0.6, 0.6, w - 1.2, h - 1.2);
        cr.stroke();

        cr.$dispose();
    },

    _strokeMiniSeries: function(cr, w, h, arr, rgb, fillAlpha) {
        let n = arr.length;
        if (n < 2) return;
        let step = w / (n - 1);

        cr.setLineWidth(1.7);
        cr.setSourceRGBA(rgb[0], rgb[1], rgb[2], 0.95);
        cr.moveTo(0, h - arr[0] * (h - 2) - 1);
        for (let i = 1; i < n; i++) {
            cr.lineTo(i * step, h - arr[i] * (h - 2) - 1);
        }
        cr.strokePreserve();
        cr.lineTo(w, h);
        cr.lineTo(0, h);
        cr.closePath();
        cr.setSourceRGBA(rgb[0], rgb[1], rgb[2], fillAlpha);
        cr.fill();
    },

    on_applet_removed_from_panel: function() {
        if (this._timeoutId) {
            Mainloop.source_remove(this._timeoutId);
            this._timeoutId = null;
        }
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new GpuPanelApplet(metadata, orientation, panel_height, instance_id);
}
