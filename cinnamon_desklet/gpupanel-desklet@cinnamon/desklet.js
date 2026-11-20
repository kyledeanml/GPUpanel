const Desklet = imports.ui.desklet;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Cairo = imports.cairo;
const St = imports.gi.St;
const PopupMenu = imports.ui.popupMenu;
const Util = imports.misc.util;

const UUID = "gpupanel-desklet@cinnamon";

function GpuPanelDesklet(metadata, desklet_id) {
    this._init(metadata, desklet_id);
}

function main(metadata, desklet_id) {
    return new GpuPanelDesklet(metadata, desklet_id);
}

GpuPanelDesklet.prototype = {
    __proto__: Desklet.Desklet.prototype,

    _init: function(metadata, desklet_id) {
        Desklet.Desklet.prototype._init.call(this, metadata, desklet_id);
        this.setHeader("GPUpanel");

        this.desklet_width = 360;
        this.desklet_height = 180;
        this.scale_size = 1.0;
        this.refresh_interval = 1;
        this.duration = 60;
        this.show_vram_line = true;
        this.show_power_line = true;

        this._resizing = false;
        this._stageMotionId = 0;
        this._stageReleaseId = 0;

        try {
            this.settings = new Settings.DeskletSettings(this, this.metadata["uuid"], desklet_id);
            this.settings.bindProperty(Settings.BindingDirection.BIDIRECTIONAL, "desklet-width", "desklet_width", this.on_size_changed);
            this.settings.bindProperty(Settings.BindingDirection.BIDIRECTIONAL, "desklet-height", "desklet_height", this.on_size_changed);
            this.settings.bindProperty(Settings.BindingDirection.BIDIRECTIONAL, "scale-size", "scale_size", this.on_size_changed);
            this.settings.bindProperty(Settings.BindingDirection.IN, "refresh-interval", "refresh_interval", this.on_setting_changed);
            this.settings.bindProperty(Settings.BindingDirection.IN, "duration", "duration", this.on_setting_changed);
            this.settings.bindProperty(Settings.BindingDirection.IN, "show-vram-line", "show_vram_line", this.on_size_changed);
            this.settings.bindProperty(Settings.BindingDirection.IN, "show-power-line", "show_power_line", this.on_size_changed);
        } catch (e) {
            global.logError("GPUpanel desklet settings error: " + e);
        }

        this._buildContextMenu();
        this._resetBuffers();
        this._setupUI();

        Mainloop.idle_add(Lang.bind(this, function() {
            this._update();
            return false;
        }));
    },

    _buildContextMenu: function() {
        this._menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Quick Size Presets Submenu in Right-Click Menu
        let sizeSubMenu = new PopupMenu.PopupSubMenuMenuItem("Resize Desktop Graph...");
        let presets = [
            ["Compact (240 × 125 px)", 240, 125],
            ["Small (300 × 150 px)", 300, 150],
            ["Standard (360 × 180 px)", 360, 180],
            ["Medium-Wide (420 × 205 px)", 420, 205],
            ["Large (480 × 235 px)", 480, 235],
            ["Extra Large (560 × 275 px)", 560, 275]
        ];
        for (let i = 0; i < presets.length; i++) {
            let [label, pw, ph] = presets[i];
            let item = new PopupMenu.PopupMenuItem(label);
            item.connect("activate", Lang.bind(this, function() {
                this.scale_size = 1.0;
                this.desklet_width = pw;
                this.desklet_height = ph;
                this._draw();
            }));
            sizeSubMenu.menu.addMenuItem(item);
        }
        this._menu.addMenuItem(sizeSubMenu);

        let launchItem = new PopupMenu.PopupMenuItem("Open GPUpanel Full Application");
        launchItem.connect("activate", Lang.bind(this, function() {
            Util.spawnCommandLine(GLib.get_home_dir() + "/gpupanel/run.sh");
        }));
        this._menu.addMenuItem(launchItem);

        let hudItem = new PopupMenu.PopupMenuItem("Open GPUpanel Mini Floating HUD");
        hudItem.connect("activate", Lang.bind(this, function() {
            Util.spawnCommandLine(GLib.get_home_dir() + "/gpupanel/run.sh --hud");
        }));
        this._menu.addMenuItem(hudItem);
    },

    _resetBuffers: function() {
        this.n_values = Math.max(20, Math.floor(this.duration / Math.max(1, this.refresh_interval)) + 1);
        this.gpu_values = new Array(this.n_values).fill(0.0);
        this.vram_values = new Array(this.n_values).fill(0.0);
        this.pwr_values = new Array(this.n_values).fill(0.0);
        if (!this.latest) {
            this.latest = {
                name: "RTX 3060",
                pstate: "P0",
                gpu_util: 0,
                vram_used: 0,
                vram_total: 12288,
                vram_pct: 0,
                temp_c: 0,
                fan_pct: 0,
                pwr_w: 0,
                pwr_lim: 170,
                clk_gfx: 0
            };
        }
    },

    _setupUI: function() {
        this.container = new Clutter.Actor({ reactive: true });

        this.titleLabel = new St.Label({ style: "font-family: sans-serif; font-weight: bold; color: #00f0ff;" });
        this.valueLabel = new St.Label({ style: "font-family: monospace; font-weight: bold; color: #ffffff;" });
        this.vramLabel = new St.Label({ style: "font-family: monospace; color: #bae6fd;" });
        this.statsLabel = new St.Label({ style: "font-family: monospace; color: #93c5fd;" });

        // Interactive Drag-to-Resize Corner Grip at bottom-right
        this.resizeGrip = new St.Bin({
            reactive: true,
            track_hover: true,
            width: 22,
            height: 22,
            style: "cursor: se-resize;"
        });
        this.resizeGrip.connect("button-press-event", Lang.bind(this, this._onResizePress));

        // Scroll wheel over desklet (Ctrl + Scroll or Scroll on grip) scales smoothly
        this.actor.connect("scroll-event", Lang.bind(this, this._onScrollResize));
        this.resizeGrip.connect("scroll-event", Lang.bind(this, this._onGripScrollResize));

        this.container.add_actor(this.titleLabel);
        this.container.add_actor(this.valueLabel);
        this.container.add_actor(this.vramLabel);
        this.container.add_actor(this.statsLabel);
        this.container.add_actor(this.resizeGrip);

        this.setContent(this.container);
    },

    _onScrollResize: function(actor, event) {
        let state = event.get_state();
        if (!(state & Clutter.ModifierType.CONTROL_MASK)) {
            return Clutter.EVENT_PROPAGATE;
        }
        return this._applyWheelDelta(event.get_scroll_direction());
    },

    _onGripScrollResize: function(actor, event) {
        return this._applyWheelDelta(event.get_scroll_direction());
    },

    _applyWheelDelta: function(dir) {
        let factor = 1.0;
        if (dir === Clutter.ScrollDirection.UP) {
            factor = 1.06;
        } else if (dir === Clutter.ScrollDirection.DOWN) {
            factor = 0.94;
        } else {
            return Clutter.EVENT_PROPAGATE;
        }
        this.desklet_width = Math.max(200, Math.min(900, Math.round(this.desklet_width * factor)));
        this.desklet_height = Math.max(100, Math.min(600, Math.round(this.desklet_height * factor)));
        this._draw();
        return Clutter.EVENT_STOP;
    },

    _onResizePress: function(actor, event) {
        if (event.get_button() !== 1) return Clutter.EVENT_PROPAGATE;

        this._resizing = true;
        let [sx, sy] = event.get_coords();
        this._dragStartX = sx;
        this._dragStartY = sy;
        let s = this.scale_size || 1.0;
        this._startW = Math.round((this.desklet_width || 360) * s);
        this._startH = Math.round((this.desklet_height || 180) * s);
        this.scale_size = 1.0;

        this._stageMotionId = global.stage.connect("motion-event", Lang.bind(this, function(stage, mEvent) {
            if (!this._resizing) return Clutter.EVENT_PROPAGATE;
            let [mx, my] = mEvent.get_coords();
            let nw = Math.max(200, Math.min(900, Math.round(this._startW + (mx - this._dragStartX))));
            let nh = Math.max(105, Math.min(600, Math.round(this._startH + (my - this._dragStartY))));
            this.desklet_width = nw;
            this.desklet_height = nh;
            this._draw();
            return Clutter.EVENT_STOP;
        }));

        this._stageReleaseId = global.stage.connect("button-release-event", Lang.bind(this, function(stage, rEvent) {
            this._stopResizeDrag();
            return Clutter.EVENT_STOP;
        }));

        return Clutter.EVENT_STOP;
    },

    _stopResizeDrag: function() {
        this._resizing = false;
        if (this._stageMotionId) {
            global.stage.disconnect(this._stageMotionId);
            this._stageMotionId = 0;
        }
        if (this._stageReleaseId) {
            global.stage.disconnect(this._stageReleaseId);
            this._stageReleaseId = 0;
        }
    },

    on_desklet_clicked: function(event) {
        if (this._resizing) return;
        Util.spawnCommandLine(GLib.get_home_dir() + "/gpupanel/run.sh");
    },

    on_size_changed: function() {
        this._draw();
    },

    on_setting_changed: function() {
        if (this.timeout) {
            Mainloop.source_remove(this.timeout);
            this.timeout = null;
        }
        this._resetBuffers();
        this._update();
    },

    on_desklet_removed: function() {
        this._stopResizeDrag();
        if (this.timeout) {
            Mainloop.source_remove(this.timeout);
            this.timeout = null;
        }
    },

    _update: function() {
        this._pollGpu();
        this._draw();
        let interval = Math.max(1, this.refresh_interval || 1);
        this.timeout = Mainloop.timeout_add_seconds(interval, Lang.bind(this, this._update));
        return false;
    },

    _pollGpu: function() {
        try {
            let proc = new Gio.Subprocess({
                argv: [
                    "/usr/bin/nvidia-smi",
                    "--query-gpu=name,pstate,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,power.draw,power.limit,clocks.current.graphics",
                    "--format=csv,noheader,nounits"
                ],
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            });
            proc.init(null);
            proc.communicate_utf8_async(null, null, (source, res) => {
                try {
                    let [ok, stdout, stderr] = source.communicate_utf8_finish(res);
                    if (!ok || !stdout) return;
                    let parts = stdout.trim().split("\n")[0].split(",").map(s => s.trim());
                    if (parts.length < 10) return;

                    let gpu_u = parseFloat(parts[2]) || 0;
                    let v_used = parseFloat(parts[3]) || 0;
                    let v_tot = Math.max(1, parseFloat(parts[4]) || 12288);
                    let v_pct = (v_used / v_tot) * 100.0;
                    let temp = parseFloat(parts[5]) || 0;
                    let fan = parseFloat(parts[6]) || 0;
                    let pwr = parseFloat(parts[7]) || 0;
                    let pwr_lim = Math.max(1, parseFloat(parts[8]) || 170);
                    let clk_g = parseInt(parts[9]) || 0;

                    this.latest = {
                        name: (parts[0] || "NVIDIA GPU").replace("NVIDIA GeForce ", ""),
                        pstate: parts[1] || "P0",
                        gpu_util: gpu_u,
                        vram_used: v_used,
                        vram_total: v_tot,
                        vram_pct: v_pct,
                        temp_c: temp,
                        fan_pct: fan,
                        pwr_w: pwr,
                        pwr_lim: pwr_lim,
                        clk_gfx: clk_g
                    };

                    this.gpu_values.push(Math.min(1.0, Math.max(0.0, gpu_u / 100.0)));
                    this.gpu_values.shift();
                    this.vram_values.push(Math.min(1.0, Math.max(0.0, v_pct / 100.0)));
                    this.vram_values.shift();
                    this.pwr_values.push(Math.min(1.0, Math.max(0.0, pwr / pwr_lim)));
                    this.pwr_values.shift();
                } catch (err) {
                    // ignore
                }
            });
        } catch (e) {
            // ignore
        }
    },

    _draw: function() {
        let ui_scale = global.ui_scale || 1;
        let s = (this.scale_size || 1.0) * ui_scale;
        let w = Math.max(200, Math.round((this.desklet_width || 360) * s));
        let h = Math.max(105, Math.round((this.desklet_height || 180) * s));

        // Proportional padding & header height that scales cleanly with any width/height
        let pad_x = Math.max(10, Math.round(w * 0.042));
        let pad_bottom = Math.max(10, Math.round(h * 0.075));
        let header_h = Math.max(34, Math.min(62, Math.round(h * 0.275)));

        let gx = pad_x;
        let gy = header_h;
        let gw = Math.max(80, w - 2 * pad_x);
        let gh = Math.max(45, h - gy - pad_bottom);
        let radius = Math.max(6, Math.min(14, Math.round(Math.min(w, h) * 0.055)));
        let lw = Math.max(1.0, Math.min(2.2, w / 280.0));
        let n = this.n_values;
        let step = gw / Math.max(1, n - 1);

        let gpu_arr = this.gpu_values;
        let vram_arr = this.vram_values;
        let pwr_arr = this.pwr_values;
        let show_vram = this.show_vram_line;
        let show_pwr = this.show_power_line;

        let canvas = new Clutter.Canvas();
        canvas.set_size(w, h);
        canvas.connect("draw", function(c, cr, cw, ch) {
            cr.save();
            cr.setOperator(Cairo.Operator.CLEAR);
            cr.paint();
            cr.restore();
            cr.setOperator(Cairo.Operator.OVER);

            let deg = Math.PI / 180.0;

            // PythonPanel Dark Neon rounded card (#0b0f19)
            cr.newSubPath();
            cr.arc(w - radius, radius, radius, -90 * deg, 0 * deg);
            cr.arc(w - radius, h - radius, radius, 0 * deg, 90 * deg);
            cr.arc(radius, h - radius, radius, 90 * deg, 180 * deg);
            cr.arc(radius, radius, radius, 180 * deg, 270 * deg);
            cr.closePath();
            cr.setSourceRGBA(0.043, 0.059, 0.098, 0.90);
            cr.fillPreserve();
            cr.setLineWidth(1.4 * lw);
            cr.setSourceRGBA(0.0, 0.941, 1.0, 0.45);
            cr.stroke();

            // Inner Graph Background (#070a14)
            cr.rectangle(gx, gy, gw, gh);
            cr.setSourceRGBA(0.027, 0.039, 0.078, 0.95);
            cr.fill();

            // Grid midlines
            cr.setLineWidth(lw * 0.75);
            cr.setSourceRGBA(0.220, 0.741, 0.973, 0.16);
            for (let i = 1; i < 4; i++) {
                let my = gy + (gh / 4.0) * i;
                cr.moveTo(gx, my);
                cr.lineTo(gx + gw, my);
                cr.stroke();
            }
            for (let i = 1; i < 5; i++) {
                let mx = gx + (gw / 5.0) * i;
                cr.moveTo(mx, gy);
                cr.lineTo(mx, gy + gh);
                cr.stroke();
            }

            // Helper to plot series
            function plotTrace(arr, r, g, b, fillA, lineW) {
                if (!arr || arr.length < 2) return;
                cr.setLineWidth(lineW);
                cr.setSourceRGBA(r, g, b, 0.96);
                cr.moveTo(gx, gy + gh - (arr[0] * (gh - 2)) - 1);
                for (let i = 1; i < arr.length; i++) {
                    cr.lineTo(gx + i * step, gy + gh - (arr[i] * (gh - 2)) - 1);
                }
                cr.strokePreserve();
                cr.lineTo(gx + gw, gy + gh);
                cr.lineTo(gx, gy + gh);
                cr.closePath();
                cr.setSourceRGBA(r, g, b, fillA);
                cr.fill();
            }

            if (show_pwr) {
                plotTrace(pwr_arr, 0.659, 0.333, 0.969, 0.12, 1.5 * lw);
            }
            if (show_vram) {
                plotTrace(vram_arr, 0.063, 0.725, 0.506, 0.22, 1.8 * lw);
            }
            plotTrace(gpu_arr, 0.0, 0.941, 1.0, 0.34, 2.2 * lw);

            // Graph frame border (#00f0ff)
            cr.setLineWidth(1.3 * lw);
            cr.setSourceRGBA(0.0, 0.941, 1.0, 0.75);
            cr.rectangle(gx, gy, gw, gh);
            cr.stroke();

            // Subtle Neon Corner Resize Grip Indicator (bottom-right)
            cr.setLineWidth(1.3);
            cr.setSourceRGBA(0.0, 0.941, 1.0, 0.55);
            cr.moveTo(w - 13, h - 5);
            cr.lineTo(w - 5, h - 13);
            cr.moveTo(w - 9, h - 5);
            cr.lineTo(w - 5, h - 9);
            cr.stroke();

            return false;
        });

        let d = this.latest;

        // Font sizes constrained by both width and header height so text NEVER overflows
        let t1_sz = Math.max(10, Math.min(Math.round(header_h * 0.34), Math.round(gw * 0.048)));
        let t2_sz = Math.max(10, Math.min(Math.round(header_h * 0.36), Math.round(gw * 0.052)));
        let t3_sz = Math.max(8, Math.min(Math.round(header_h * 0.25), Math.round(gw * 0.033)));

        let row1_y = Math.max(4, Math.round(header_h * 0.12));
        let row2_y = Math.max(row1_y + t1_sz + 2, Math.round(header_h * 0.54));

        // Top Row: Left = GPU Model + P-State, Right = Core %
        this.titleLabel.set_text("GPU · " + d.name + " [" + d.pstate + "]");
        this.titleLabel.style = "font-family: sans-serif; font-weight: bold; color: #00f0ff; font-size: " + t1_sz + "px;";
        this.titleLabel.set_position(gx, row1_y);

        this.valueLabel.set_text(Math.round(d.gpu_util) + "%");
        this.valueLabel.style = "font-family: monospace; font-weight: bold; color: #ffffff; font-size: " + t2_sz + "px;";
        this.valueLabel.set_position(Math.max(gx, gx + gw - this.valueLabel.get_width()), row1_y);

        // Second Row: Split cleanly into Left (VRAM) and Right (Temp · Power · Clock) aligned inside [gx, gx + gw]
        let vram_str = "VRAM " + (d.vram_used / 1024.0).toFixed(2) + "/" + (d.vram_total / 1024.0).toFixed(0) + "G (" + d.vram_pct.toFixed(0) + "%)";
        let stats_str = Math.round(d.temp_c) + "°C · " + d.pwr_w.toFixed(0) + "W · " + d.clk_gfx + "MHz";

        this.vramLabel.set_text(vram_str);
        this.vramLabel.style = "font-family: monospace; color: #bae6fd; font-size: " + t3_sz + "px;";
        this.vramLabel.set_position(gx, row2_y);

        this.statsLabel.set_text(stats_str);
        this.statsLabel.style = "font-family: monospace; color: #93c5fd; font-size: " + t3_sz + "px;";
        this.statsLabel.set_position(Math.max(gx, gx + gw - this.statsLabel.get_width()), row2_y);

        // Position bottom-right resize grip
        this.resizeGrip.set_position(w - 22, h - 22);

        canvas.invalidate();
        this.container.set_content(canvas);
        this.container.set_size(w, h);
    }
};
