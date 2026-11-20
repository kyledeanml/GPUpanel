#!/usr/bin/env python3
"""
Unit & Integration Test Suite for GPUpanel
Verifies NVML telemetry engine, history buffer, CSV/JSON export,
Cairo widget instantiation, and Cinnamon Applet / Desklet bundle integrity.
"""

import json
import os
import tempfile
import unittest

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gpu_telemetry import GpuTelemetryEngine, GpuHistoryBuffer, METRIC_CHANNELS
from gpu_graphs import GpuGaugeCard, GpuResourceGraph, VramAllocationBar
from cinnamon_manager import CinnamonAppletManager


class TestGpuPanel(unittest.TestCase):

    def test_telemetry_engine_poll(self):
        engine = GpuTelemetryEngine()
        self.assertGreaterEqual(engine.get_device_count(), 1)
        spec = engine.get_device_spec(0)
        self.assertTrue(len(spec.name) > 0)
        self.assertGreater(spec.vram_total_mib, 0)

        snap = engine.poll(0, include_processes=True)
        self.assertGreaterEqual(snap.gpu_util, 0.0)
        self.assertLessEqual(snap.gpu_util, 100.0)
        self.assertGreater(snap.vram_total_mib, 0.0)
        self.assertGreaterEqual(snap.temp_c, 0.0)
        self.assertTrue(snap.pstate.startswith("P"))
        engine.shutdown()

    def test_history_buffer_and_exports(self):
        engine = GpuTelemetryEngine()
        buf = GpuHistoryBuffer(max_points=60)
        for _ in range(5):
            buf.push(engine.poll(0, include_processes=False))
        engine.shutdown()

        for key in METRIC_CHANNELS:
            raw = buf.get_raw_series(key, count=60)
            norm = buf.get_normalized_series(key, count=60)
            stats = buf.get_channel_stats(key)
            self.assertEqual(len(raw), 60)
            self.assertEqual(len(norm), 60)
            self.assertIn("current", stats)
            self.assertIn("max", stats)

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "out.csv")
            json_path = os.path.join(tmp, "out.json")
            buf.export_csv(csv_path)
            buf.export_json(json_path)
            self.assertTrue(os.path.isfile(csv_path))
            self.assertTrue(os.path.isfile(json_path))
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_cairo_graph_widgets(self):
        buf = GpuHistoryBuffer(max_points=60)
        engine = GpuTelemetryEngine()
        snap = engine.poll(0)
        buf.push(snap)
        engine.shutdown()

        gauge = GpuGaugeCard("GPU Core", "gpu_util", (0.0, 0.941, 1.0))
        gauge.update_State(snap.gpu_util, "20%", "Mem: 7%", "Peak: 25%", [0.2, 0.25])

        graph = GpuResourceGraph(
            title="Test Graph",
            subtitle="Test Subtitle",
            history=buf,
            channels=["gpu_util", "vram_pct"],
        )
        graph.set_zoom_scale(1.2)

        vbar = VramAllocationBar()
        vbar.update_snapshot(snap)

    def test_cinnamon_applet_and_desklet_bundles(self):
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        mgr = CinnamonAppletManager(repo_dir)
        self.assertTrue(os.path.isfile(os.path.join(mgr.applet_src, "applet.js")))
        self.assertTrue(os.path.isfile(os.path.join(mgr.applet_src, "metadata.json")))
        self.assertTrue(os.path.isfile(os.path.join(mgr.desklet_src, "desklet.js")))
        self.assertTrue(os.path.isfile(os.path.join(mgr.desklet_src, "metadata.json")))


if __name__ == "__main__":
    unittest.main()
