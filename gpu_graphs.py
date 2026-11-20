#!/usr/bin/env python3
"""
GPUpanel Cairo Resource Graph Widgets
Retina Vision (HiDPI subpixel anti-aliased) Cairo real-time oscilloscope graphs,
radial neon gauge cards, and segmented per-process VRAM allocation bars
built in the PythonPanel Dark Neon aesthetic.
"""

import math
from typing import Dict, List, Optional, Tuple

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk
import cairo

from gpu_telemetry import GpuHistoryBuffer, GpuSnapshot, METRIC_CHANNELS


def _rounded_rect(cr: cairo.Context, x: float, y: float, w: float, h: float, r: float):
    r = min(r, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class GpuGaugeCard(Gtk.DrawingArea):
    """
    Neon radial arc gauge + mini sparkline KPI card for the top telemetry strip.
    """

    def __init__(self, title: str, channel_key: str, rgb: Tuple[float, float, float]):
        super().__init__()
        self.title = title
        self.channel_key = channel_key
        self.rgb = rgb
        self.pct: float = 0.0
        self.primary_text: str = "0%"
        self.secondary_text: str = ""
        self.peak_text: str = "Peak: 0%"
        self.spark_values: List[float] = [0.0] * 40
        self.zoom_scale: float = 1.0

        self.set_size_request(155, 112)
        self.set_hexpand(True)
        self.connect("draw", self._on_draw)

    def set_zoom_scale(self, scale: float):
        val = float(scale) if math.isfinite(float(scale)) else 1.0
        self.zoom_scale = max(0.75, min(2.0, val))
        self.queue_draw()

    def update_State(
        self,
        pct: float,
        primary_text: str,
        secondary_text: str,
        peak_text: str,
        spark_values: List[float],
    ):
        safe_pct = float(pct) if math.isfinite(float(pct)) else 0.0
        self.pct = max(0.0, min(100.0, safe_pct))
        self.primary_text = str(primary_text or "")
        self.secondary_text = str(secondary_text or "")
        self.peak_text = str(peak_text or "")
        if spark_values:
            self.spark_values = [
                max(0.0, min(1.0, float(v))) if math.isfinite(float(v)) else 0.0
                for v in spark_values[-48:]
            ]
        self.queue_draw()

    def _on_draw(self, _widget, cr: cairo.Context):
        alloc = self.get_allocation()
        w = float(alloc.width)
        h = float(alloc.height)
        r, g, b = self.rgb
        s = self.zoom_scale

        cr.set_antialias(cairo.ANTIALIAS_BEST)

        # Card background
        _rounded_rect(cr, 2, 2, w - 4, h - 4, 8)
        pat_bg = cairo.LinearGradient(0, 0, 0, h)
        pat_bg.add_color_stop_rgba(0.0, 0.067, 0.094, 0.165, 0.96)  # #111827
        pat_bg.add_color_stop_rgba(1.0, 0.039, 0.055, 0.098, 0.98)  # #0a0e19
        cr.set_source(pat_bg)
        cr.fill_preserve()

        # Neon border
        cr.set_line_width(1.2)
        cr.set_source_rgba(r, g, b, 0.42)
        cr.stroke()

        # Subtle background sparkline at the bottom of the card
        if len(self.spark_values) > 1:
            spark_h = h * 0.28
            spark_y0 = h - 5
            step_x = (w - 12) / max(1, len(self.spark_values) - 1)

            cr.new_path()
            for i, val in enumerate(self.spark_values):
                px = 6 + i * step_x
                py = spark_y0 - (max(0.0, min(1.0, val)) * spark_h)
                if i == 0:
                    cr.move_to(px, py)
                else:
                    cr.line_to(px, py)
            cr.set_line_width(1.4)
            cr.set_source_rgba(r, g, b, 0.45)
            cr.stroke_preserve()

            cr.line_to(w - 6, spark_y0)
            cr.line_to(6, spark_y0)
            cr.close_path()
            fill_pat = cairo.LinearGradient(0, spark_y0 - spark_h, 0, spark_y0)
            fill_pat.add_color_stop_rgba(0.0, r, g, b, 0.20)
            fill_pat.add_color_stop_rgba(1.0, r, g, b, 0.01)
            cr.set_source(fill_pat)
            cr.fill()

        # Left radial gauge arc
        cx = 36.0
        cy = h * 0.50
        radius = min(24.0, h * 0.27)
        start_ang = 0.75 * math.pi
        end_ang = 2.25 * math.pi

        # Track arc
        cr.set_line_width(4.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(0.118, 0.161, 0.231, 0.9)
        cr.arc(cx, cy, radius, start_ang, end_ang)
        cr.stroke()

        # Active neon arc
        active_end = start_ang + (end_ang - start_ang) * (self.pct / 100.0)
        if self.pct > 0.2:
            # Outer soft glow
            cr.set_line_width(7.5)
            cr.set_source_rgba(r, g, b, 0.24)
            cr.arc(cx, cy, radius, start_ang, active_end)
            cr.stroke()

            # Core arc
            cr.set_line_width(4.5)
            cr.set_source_rgba(r, g, b, 0.98)
            cr.arc(cx, cy, radius, start_ang, active_end)
            cr.stroke()

        # Percentage inside ring
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.0 * min(1.2, s))
        pct_label = f"{int(round(self.pct))}%"
        ext = cr.text_extents(pct_label)
        cr.set_source_rgba(0.94, 0.98, 1.0, 0.95)
        cr.move_to(cx - ext.width / 2.0 - ext.x_bearing, cy - ext.height / 2.0 - ext.y_bearing)
        cr.show_text(pct_label)

        # Text column on the right
        tx = 68.0
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.0 * min(1.25, s))
        cr.set_source_rgba(r, g, b, 0.95)
        cr.move_to(tx, 21)
        cr.show_text(self.title.upper())

        # Primary large readout
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(16.0 * min(1.3, s))
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.98)
        cr.move_to(tx, 44)
        cr.show_text(self.primary_text)

        # Secondary detail line
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5 * min(1.2, s))
        cr.set_source_rgba(0.65, 0.78, 0.92, 0.92)
        cr.move_to(tx, 62)
        cr.show_text(self.secondary_text)

        # Peak / status line
        cr.set_font_size(9.5 * min(1.2, s))
        cr.set_source_rgba(0.58, 0.64, 0.72, 0.85)
        cr.move_to(tx, 79)
        cr.show_text(self.peak_text)
        return False


class GpuResourceGraph(Gtk.DrawingArea):
    """
    High-DPI Cairo time-series oscilloscope graph widget in PythonPanel Dark Neon aesthetic.
    Supports single, dual, or multi-channel overlay rendering with interactive mouse hover crosshair.
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        history: GpuHistoryBuffer,
        channels: List[str],
        y_unit: str = "%",
        fixed_max: Optional[float] = 100.0,
        min_height: int = 190,
    ):
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.history = history
        self.channels = list(channels)
        self.enabled_channels = {ch: True for ch in channels}
        self.y_unit = y_unit
        self.fixed_max = fixed_max
        self.zoom_scale: float = 1.0
        self.show_grid: bool = True
        self.show_area_fill: bool = True
        self.smooth_curves: bool = True
        self.poll_interval_sec: float = 0.5

        self._hover_x: Optional[float] = None
        self._hover_y: Optional[float] = None

        self.set_size_request(280, min_height)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.add_events(
            Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("leave-notify-event", self._on_leave)

    def set_channel_enabled(self, channel: str, enabled: bool):
        self.enabled_channels[channel] = bool(enabled)
        self.queue_draw()

    def set_zoom_scale(self, scale: float):
        self.zoom_scale = max(0.75, min(2.2, scale))
        self.queue_draw()

    def _on_motion(self, _widget, event: Gdk.EventMotion):
        self._hover_x = event.x
        self._hover_y = event.y
        self.queue_draw()
        return False

    def _on_leave(self, _widget, _event):
        self._hover_x = None
        self._hover_y = None
        self.queue_draw()
        return False

    def _compute_ceiling(self, active_channels: List[str]) -> float:
        if self.fixed_max is not None and self.fixed_max > 0:
            return self.fixed_max
        peak = 10.0
        for ch in active_channels:
            raw = self.history.get_raw_series(ch)
            if raw:
                peak = max(peak, max(raw))
        # Round ceiling up to a clean readable value
        for threshold in (25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0):
            if peak * 1.15 <= threshold:
                return threshold
        return max(100.0, peak * 1.2)

    def _on_draw(self, _widget, cr: cairo.Context):
        alloc = self.get_allocation()
        w = float(alloc.width)
        h = float(alloc.height)
        s = self.zoom_scale

        cr.set_antialias(cairo.ANTIALIAS_BEST)

        active_channels = [c for c in self.channels if self.enabled_channels.get(c, True)]
        primary_meta = METRIC_CHANNELS.get(self.channels[0], METRIC_CHANNELS["gpu_util"])
        pr, pg, pb = primary_meta["rgb"]

        # 1. Outer Dark Neon Card Background
        _rounded_rect(cr, 2, 2, w - 4, h - 4, 9)
        bg_grad = cairo.LinearGradient(0, 0, 0, h)
        bg_grad.add_color_stop_rgba(0.0, 0.051, 0.075, 0.133, 0.97)  # #0d1322
        bg_grad.add_color_stop_rgba(1.0, 0.027, 0.039, 0.078, 0.99)  # #070a14
        cr.set_source(bg_grad)
        cr.fill_preserve()

        cr.set_line_width(1.2)
        cr.set_source_rgba(pr, pg, pb, 0.35)
        cr.stroke()

        # 2. Header Region
        header_h = 34.0 * min(1.25, s)
        pad_left = 46.0 * min(1.2, s)
        pad_right = 14.0
        pad_bottom = 22.0 * min(1.2, s)
        gx = pad_left
        gy = header_h + 6.0
        gw = max(40.0, w - pad_left - pad_right)
        gh = max(40.0, h - gy - pad_bottom)

        # Title & Subtitle
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.5 * min(1.3, s))
        cr.set_source_rgba(pr, pg, pb, 0.98)
        cr.move_to(14, 18 * min(1.2, s))
        cr.show_text(self.title)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9.5 * min(1.25, s))
        cr.set_source_rgba(0.58, 0.64, 0.72, 0.88)
        cr.move_to(14, 31 * min(1.2, s))
        cr.show_text(self.subtitle)

        # Live Legend Badges in Top-Right
        badge_x = w - 14.0
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.5 * min(1.25, s))
        for ch in reversed(active_channels):
            meta = METRIC_CHANNELS.get(ch, primary_meta)
            cr_r, cr_g, cr_b = meta["rgb"]
            stats = self.history.get_channel_stats(ch)
            fmt = str(meta.get("format", "{:.1f}%"))
            val_txt = fmt.format(stats["current"])
            label_txt = f"{meta['short']}: {val_txt}"
            ext = cr.text_extents(label_txt)
            bw = ext.width + 18
            bx = badge_x - bw
            by = 8.0
            bh = 20.0 * min(1.2, s)

            if bx < 165:
                break

            _rounded_rect(cr, bx, by, bw, bh, 4)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 0.14)
            cr.fill_preserve()
            cr.set_line_width(1.0)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 0.55)
            cr.stroke()

            # Color dot
            cr.arc(bx + 7, by + bh / 2.0, 3.0, 0, 2 * math.pi)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 1.0)
            cr.fill()

            cr.set_source_rgba(0.95, 0.98, 1.0, 0.96)
            cr.move_to(bx + 13, by + bh / 2.0 - ext.height / 2.0 - ext.y_bearing)
            cr.show_text(label_txt)

            badge_x = bx - 6.0

        # 3. Plot Canvas Box
        _rounded_rect(cr, gx, gy, gw, gh, 5)
        cr.set_source_rgba(0.020, 0.031, 0.063, 0.92)  # Deep oscilloscope black-navy
        cr.fill_preserve()
        cr.set_line_width(1.0)
        cr.set_source_rgba(0.0, 0.941, 1.0, 0.24)
        cr.stroke()

        ceil_val = self._compute_ceiling(active_channels)

        # 4. Oscilloscope Grid & Y-Axis Labels
        if self.show_grid:
            cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(8.8 * min(1.2, s))
            h_steps = 4
            for i in range(h_steps + 1):
                frac = i / float(h_steps)
                ly = gy + gh * (1.0 - frac)
                if 0 < i < h_steps:
                    cr.save()
                    cr.set_dash([4.0, 4.0])
                    cr.set_line_width(0.8)
                    cr.set_source_rgba(0.220, 0.741, 0.973, 0.16)
                    cr.move_to(gx, ly)
                    cr.line_to(gx + gw, ly)
                    cr.stroke()
                    cr.restore()

                # Y-axis tick label
                y_val = ceil_val * frac
                if ceil_val >= 100:
                    y_lbl = f"{int(round(y_val))}{self.y_unit}"
                else:
                    y_lbl = f"{y_val:.0f}{self.y_unit}"
                ext = cr.text_extents(y_lbl)
                cr.set_source_rgba(0.58, 0.64, 0.72, 0.80)
                cr.move_to(gx - ext.width - 6, ly + ext.height / 2.0)
                cr.show_text(y_lbl)

            v_steps = 6
            for i in range(1, v_steps):
                lx = gx + gw * (i / float(v_steps))
                cr.save()
                cr.set_dash([3.0, 4.0])
                cr.set_line_width(0.8)
                cr.set_source_rgba(0.220, 0.741, 0.973, 0.13)
                cr.move_to(lx, gy)
                cr.line_to(lx, gy + gh)
                cr.stroke()
                cr.restore()

        # Time axis labels along bottom
        n_pts = self.history.max_points
        total_sec = int(round(n_pts * self.poll_interval_sec))
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(8.5 * min(1.2, s))
        cr.set_source_rgba(0.45, 0.55, 0.68, 0.85)
        cr.move_to(gx, gy + gh + 14)
        cr.show_text(f"-{total_sec}s")
        mid_lbl = f"-{total_sec // 2}s"
        ext_m = cr.text_extents(mid_lbl)
        cr.move_to(gx + gw / 2.0 - ext_m.width / 2.0, gy + gh + 14)
        cr.show_text(mid_lbl)
        now_lbl = "Now"
        ext_n = cr.text_extents(now_lbl)
        cr.move_to(gx + gw - ext_n.width, gy + gh + 14)
        cr.show_text(now_lbl)

        # 5. Clip to Plot Area and Render Glowing Telemetry Traces
        cr.save()
        _rounded_rect(cr, gx, gy, gw, gh, 5)
        cr.clip()

        step_x = gw / max(1, n_pts - 1)
        channel_points: Dict[str, List[Tuple[float, float, float]]] = {}

        for ch in active_channels:
            meta = METRIC_CHANNELS.get(ch, primary_meta)
            cr_r, cr_g, cr_b = meta["rgb"]
            raw_vals = self.history.get_raw_series(ch, count=n_pts)
            norm_vals = self.history.get_normalized_series(
                ch,
                count=n_pts,
                dynamic_max=ceil_val if self.fixed_max is None else None,
            )

            pts: List[Tuple[float, float, float]] = []
            for idx, (nv, rv) in enumerate(zip(norm_vals, raw_vals)):
                px = gx + idx * step_x
                py = gy + gh - (nv * (gh - 4.0)) - 2.0
                pts.append((px, py, rv))
            channel_points[ch] = pts

            if len(pts) < 2:
                continue

            # Translucent gradient area fill underneath trace
            if self.show_area_fill:
                self._trace_path(cr, pts)
                cr.line_to(pts[-1][0], gy + gh)
                cr.line_to(pts[0][0], gy + gh)
                cr.close_path()
                area_grad = cairo.LinearGradient(0, gy, 0, gy + gh)
                alpha_top = 0.28 if len(active_channels) <= 2 else 0.16
                area_grad.add_color_stop_rgba(0.0, cr_r, cr_g, cr_b, alpha_top)
                area_grad.add_color_stop_rgba(0.75, cr_r, cr_g, cr_b, alpha_top * 0.25)
                area_grad.add_color_stop_rgba(1.0, cr_r, cr_g, cr_b, 0.01)
                cr.set_source(area_grad)
                cr.fill()

            # Outer neon glow stroke
            self._trace_path(cr, pts)
            cr.set_line_width(4.5)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 0.24)
            cr.stroke()

            # Crisp core stroke
            self._trace_path(cr, pts)
            cr.set_line_width(2.1)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 0.96)
            cr.stroke()

            # Live endpoint glowing dot
            lx, ly, _ = pts[-1]
            cr.arc(lx, ly, 4.2, 0, 2 * math.pi)
            cr.set_source_rgba(cr_r, cr_g, cr_b, 0.35)
            cr.fill()
            cr.arc(lx, ly, 2.3, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
            cr.fill()

        # 6. Interactive Hover Crosshair & Value Inspection Tooltip
        if (
            self._hover_x is not None
            and gx <= self._hover_x <= gx + gw
            and active_channels
        ):
            idx = int(round((self._hover_x - gx) / max(0.001, step_x)))
            idx = max(0, min(n_pts - 1, idx))
            cx = gx + idx * step_x

            # Vertical crosshair line
            cr.set_line_width(1.1)
            cr.set_source_rgba(0.0, 0.941, 1.0, 0.65)
            cr.move_to(cx, gy)
            cr.line_to(cx, gy + gh)
            cr.stroke()

            tooltip_rows: List[Tuple[Tuple[float, float, float], str]] = []
            sec_ago = (n_pts - 1 - idx) * self.poll_interval_sec
            for ch in active_channels:
                pts = channel_points.get(ch, [])
                if idx < len(pts):
                    px, py, rv = pts[idx]
                    meta = METRIC_CHANNELS.get(ch, primary_meta)
                    cr_r, cr_g, cr_b = meta["rgb"]
                    cr.arc(px, py, 4.2, 0, 2 * math.pi)
                    cr.set_source_rgba(cr_r, cr_g, cr_b, 0.95)
                    cr.fill()
                    cr.arc(px, py, 2.0, 0, 2 * math.pi)
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                    cr.fill()
                    fmt = str(meta.get("format", "{:.1f}%"))
                    tooltip_rows.append(((cr_r, cr_g, cr_b), f"{meta['short']}: {fmt.format(rv)}"))

            if tooltip_rows:
                cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(9.5 * min(1.2, s))
                tw = 132.0
                th = 22.0 + len(tooltip_rows) * 16.0
                tx = cx + 12.0
                if tx + tw > gx + gw - 6:
                    tx = cx - tw - 12.0
                ty = gy + 8.0

                _rounded_rect(cr, tx, ty, tw, th, 6)
                cr.set_source_rgba(0.043, 0.059, 0.098, 0.94)
                cr.fill_preserve()
                cr.set_line_width(1.1)
                cr.set_source_rgba(0.0, 0.941, 1.0, 0.75)
                cr.stroke()

                cr.set_source_rgba(0.58, 0.78, 0.95, 0.95)
                cr.move_to(tx + 8, ty + 14)
                cr.show_text(f"T -{sec_ago:.1f}s")

                for r_i, ((cr_r, cr_g, cr_b), row_txt) in enumerate(tooltip_rows):
                    ry = ty + 30 + r_i * 15
                    cr.arc(tx + 11, ry - 3.5, 3.0, 0, 2 * math.pi)
                    cr.set_source_rgba(cr_r, cr_g, cr_b, 1.0)
                    cr.fill()
                    cr.set_source_rgba(0.96, 0.98, 1.0, 0.96)
                    cr.move_to(tx + 19, ry)
                    cr.show_text(row_txt)

        cr.restore()
        return False

    @staticmethod
    def _trace_path(cr: cairo.Context, pts: List[Tuple[float, float, float]]):
        cr.new_path()
        if not pts:
            return
        cr.move_to(pts[0][0], pts[0][1])
        for px, py, _ in pts[1:]:
            cr.line_to(px, py)


class VramAllocationBar(Gtk.DrawingArea):
    """
    Segmented neon horizontal bar chart visualizing per-process VRAM allocation vs free VRAM.
    """

    SEGMENT_PALETTE = [
        (0.0, 0.941, 1.0),    # Neon Cyan
        (0.063, 0.725, 0.506),# Emerald
        (0.659, 0.333, 0.969),# Violet
        (0.220, 0.741, 0.973),# Sky Blue
        (0.961, 0.620, 0.043),# Amber
        (0.984, 0.443, 0.522),# Coral
    ]

    def __init__(self):
        super().__init__()
        self._snapshot: Optional[GpuSnapshot] = None
        self.set_size_request(280, 68)
        self.set_hexpand(True)
        self.connect("draw", self._on_draw)

    def update_snapshot(self, snap: GpuSnapshot):
        self._snapshot = snap
        self.queue_draw()

    def _on_draw(self, _widget, cr: cairo.Context):
        alloc = self.get_allocation()
        w = float(alloc.width)
        h = float(alloc.height)

        cr.set_antialias(cairo.ANTIALIAS_BEST)
        _rounded_rect(cr, 2, 2, w - 4, h - 4, 8)
        cr.set_source_rgba(0.051, 0.075, 0.133, 0.96)
        cr.fill_preserve()
        cr.set_line_width(1.1)
        cr.set_source_rgba(0.063, 0.725, 0.506, 0.4)
        cr.stroke()

        snap = self._snapshot
        if not snap:
            return False

        total = max(1.0, snap.vram_total_mib)
        used = snap.vram_used_mib
        pct = snap.vram_pct

        # Header text
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.5)
        cr.set_source_rgba(0.063, 0.725, 0.506, 0.98)
        cr.move_to(14, 18)
        cr.show_text(
            f"VRAM BREAKDOWN — {used:.0f} / {total:.0f} MiB ({used / 1024.0:.2f} / {total / 1024.0:.1f} GiB · {pct:.1f}%)"
        )

        bar_x = 14.0
        bar_y = 26.0
        bar_w = max(40.0, w - 28.0)
        bar_h = 16.0

        # Background bar
        _rounded_rect(cr, bar_x, bar_y, bar_w, bar_h, 5)
        cr.set_source_rgba(0.08, 0.11, 0.18, 0.95)
        cr.fill_preserve()
        cr.set_line_width(1.0)
        cr.set_source_rgba(0.0, 0.941, 1.0, 0.25)
        cr.stroke()

        cr.save()
        _rounded_rect(cr, bar_x, bar_y, bar_w, bar_h, 5)
        cr.clip()

        cur_x = bar_x
        legend_items: List[Tuple[Tuple[float, float, float], str]] = []
        accounted_mib = 0.0

        for idx, proc in enumerate(snap.processes[:6]):
            if proc.vram_mib <= 0:
                continue
            seg_w = max(3.0, (proc.vram_mib / total) * bar_w)
            rgb = self.SEGMENT_PALETTE[idx % len(self.SEGMENT_PALETTE)]
            cr.rectangle(cur_x, bar_y, seg_w, bar_h)
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.88)
            cr.fill()
            cur_x += seg_w
            accounted_mib += proc.vram_mib
            legend_items.append((rgb, f"{proc.name} ({proc.vram_mib:.0f}M)"))

        rem_used = max(0.0, used - accounted_mib)
        if rem_used > 5.0:
            seg_w = max(2.0, (rem_used / total) * bar_w)
            rgb = (0.38, 0.52, 0.72)
            cr.rectangle(cur_x, bar_y, seg_w, bar_h)
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.75)
            cr.fill()
            legend_items.append((rgb, f"Driver/Other ({rem_used:.0f}M)"))

        cr.restore()

        # Bottom legend strip
        lx = 14.0
        ly = 56.0
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9.2)
        for rgb, lbl in legend_items:
            ext = cr.text_extents(lbl)
            if lx + ext.width + 20 > w - 10:
                break
            cr.arc(lx + 4, ly - 3.5, 3.2, 0, 2 * math.pi)
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 1.0)
            cr.fill()
            cr.set_source_rgba(0.82, 0.90, 0.98, 0.92)
            cr.move_to(lx + 11, ly)
            cr.show_text(lbl)
            lx += ext.width + 22.0

        return False
