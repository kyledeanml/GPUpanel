#!/usr/bin/env python3
"""
Unit & Integration Test Suite for GPUpanel
Verifies NVML telemetry engine, history buffer, CSV/JSON export,
Cairo widget instantiation, and Cinnamon Applet / Desklet bundle integrity.
"""

import json
import math
import os
import stat
import tempfile
import unittest

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gpu_telemetry import (
    GpuTelemetryEngine,
    GpuHistoryBuffer,
    GpuSnapshot,
    METRIC_CHANNELS,
    clean_gpu_name,
    sanitize_csv_cell,
)
from gpu_graphs import GpuGaugeCard, GpuResourceGraph, VramAllocationBar
from cinnamon_manager import CinnamonAppletManager
from gpupanel import GpuPanelWindow


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


class TestSecurityAndIntegrityHardening(unittest.TestCase):
    """Penetration, attack-vector, and robustness tests for GPUpanel."""

    def test_csv_formula_injection_sanitization_and_atomic_exports(self):
        for payload in (
            "=cmd|' /C calc'!A0",
            "+SUM(A1:A10)",
            "-2+3+cmd",
            "@IMPORTXML(A1,A2)",
            "\t=1+1",
        ):
            sanitized = sanitize_csv_cell(payload)
            self.assertTrue(str(sanitized).startswith("'"), f"Failed to neutralize {payload!r}")

        self.assertEqual(sanitize_csv_cell("-12.5"), "-12.5")
        self.assertEqual(sanitize_csv_cell("GeForce RTX 3060"), "GeForce RTX 3060")

        buf = GpuHistoryBuffer(max_points=30)
        buf.push(GpuSnapshot(gpu_name="=EVIL_FORMULA()", pstate="@P0"))

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "telemetry.csv")
            json_path = os.path.join(tmpdir, "telemetry.json")
            buf.export_csv(csv_path)
            buf.export_json(json_path)

            with open(csv_path, "r", encoding="utf-8") as f:
                csv_text = f.read()
            self.assertIn("'=EVIL_FORMULA()", csv_text)
            self.assertIn("'@P0", csv_text)
            self.assertEqual(stat.S_IMODE(os.stat(csv_path).st_mode), 0o644)

            # Permission preservation on atomic overwrite
            os.chmod(csv_path, 0o600)
            buf.export_csv(csv_path)
            self.assertEqual(stat.S_IMODE(os.stat(csv_path).st_mode), 0o600)

            # Reject null byte, directory, and FIFO export targets
            with self.assertRaises(ValueError):
                buf.export_csv(os.path.join(tmpdir, "bad\x00.csv"))
            with self.assertRaises(IsADirectoryError):
                buf.export_csv(tmpdir)
            with self.assertRaises(IsADirectoryError):
                buf.export_json(tmpdir)

            fifo_path = os.path.join(tmpdir, "pipe.csv")
            os.mkfifo(fifo_path)
            with self.assertRaises(ValueError):
                buf.export_csv(fifo_path)
            with self.assertRaises(ValueError):
                buf.export_json(fifo_path)

    def test_nan_and_inf_telemetry_and_gauge_resilience(self):
        self.assertEqual(GpuTelemetryEngine._safe_float("nan", 5.0), 5.0)
        self.assertEqual(GpuTelemetryEngine._safe_float("inf", 5.0), 5.0)
        self.assertEqual(GpuTelemetryEngine._safe_float("-inf", 5.0), 5.0)
        self.assertEqual(GpuTelemetryEngine._safe_int("nan", 7), 7)
        self.assertEqual(GpuTelemetryEngine._safe_int("inf", 7), 7)

        buf = GpuHistoryBuffer(max_points=30)
        snap = GpuSnapshot(gpu_util=float("nan"), pcie_tx_mbs=float("inf"), pcie_rx_mbs=10.0)
        buf.push(snap)
        self.assertEqual(buf.extract_value(snap, "gpu_util"), 0.0)
        self.assertEqual(buf.extract_value(snap, "pcie_total_mbs"), 0.0)

        gauge = GpuGaugeCard("GPU Core", "gpu_util", (0.0, 0.941, 1.0))
        gauge.update_State(float("nan"), "NaN%", "", "", [float("nan"), float("inf"), 0.5])
        self.assertEqual(gauge.pct, 0.0)
        self.assertTrue(all(math.isfinite(v) for v in gauge.spark_values))

    def test_pid_termination_validation_blocks_reserved_and_system_processes(self):
        for bad_pid in (-1, 0, 1, os.getpid(), True, "123"):
            allowed, _reason = GpuPanelWindow.validate_terminable_pid(bad_pid, "python3")
            self.assertFalse(allowed, f"PID {bad_pid!r} should have been rejected")

        for sys_proc in ("Xorg", "Xwayland", "cinnamon", "cinnamon-session", "systemd", "dbus-daemon"):
            allowed, _reason = GpuPanelWindow.validate_terminable_pid(99999, sys_proc)
            self.assertFalse(allowed, f"Protected process {sys_proc} should have been rejected")

    def test_proc_inspection_control_char_sanitization(self):
        self.assertEqual(clean_gpu_name("NVIDIA\x00\x1b[31m GeForce RTX 3060\n"), "[31m GeForce RTX 3060")
        engine = GpuTelemetryEngine()
        try:
            self.assertEqual(engine._inspect_pid(-5), ("unknown", "unknown", "user"))
            self.assertEqual(engine._inspect_pid(0), ("unknown", "unknown", "user"))
            name, cmdline, user = engine._inspect_pid(os.getpid())
            self.assertTrue(len(name) > 0)
            self.assertTrue(len(user) > 0)
        finally:
            engine.shutdown()

    def test_cinnamon_manager_atomic_json_rejects_symlinks_and_fifos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "0.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"desklet-width": {"value": 360}}, f)
            os.chmod(cfg_file, 0o600)

            CinnamonAppletManager._atomic_write_json(cfg_file, {"desklet-width": {"value": 420}})
            self.assertEqual(stat.S_IMODE(os.stat(cfg_file).st_mode), 0o600)
            with open(cfg_file, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["desklet-width"]["value"], 420)

            sym_file = os.path.join(tmpdir, "symlink.json")
            os.symlink(cfg_file, sym_file)
            with self.assertRaises(ValueError):
                CinnamonAppletManager._atomic_write_json(sym_file, {})

            fifo_file = os.path.join(tmpdir, "fifo.json")
            os.mkfifo(fifo_file)
            with self.assertRaises(ValueError):
                CinnamonAppletManager._atomic_write_json(fifo_file, {})


if __name__ == "__main__":
    unittest.main()
