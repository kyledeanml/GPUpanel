#!/usr/bin/env python3
"""
GPUpanel Telemetry Engine
High-performance NVIDIA GPU resource monitoring via direct NVML (libnvidia-ml.so.1)
with automatic fallback to nvidia-smi CLI and deterministic simulation mode.
"""

import ctypes
import csv
import json
import math
import os
import pwd
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [
        ("gpu", ctypes.c_uint),
        ("memory", ctypes.c_uint),
    ]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvmlPciInfo(ctypes.Structure):
    _fields_ = [
        ("busIdLegacy", ctypes.c_char * 16),
        ("domain", ctypes.c_uint),
        ("bus", ctypes.c_uint),
        ("device", ctypes.c_uint),
        ("pciDeviceId", ctypes.c_uint),
        ("pciSubSystemId", ctypes.c_uint),
        ("busId", ctypes.c_char * 32),
    ]


class _NvmlProcessInfoV2(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedGpuMemory", ctypes.c_ulonglong),
        ("gpuInstanceId", ctypes.c_uint),
        ("computeInstanceId", ctypes.c_uint),
    ]


class _NvmlProcessInfoV1(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedGpuMemory", ctypes.c_ulonglong),
    ]


@dataclass
class GpuProcess:
    """Represents an active Graphics or Compute process on the NVIDIA GPU."""
    pid: int
    proc_type: str  # "G", "C", or "C+G"
    name: str
    cmdline: str
    user: str
    vram_mib: float
    vram_pct: float


@dataclass
class GpuDeviceSpec:
    """Static and semi-static hardware specifications for an NVIDIA GPU."""
    index: int = 0
    name: str = "NVIDIA GeForce GPU"
    uuid: str = "GPU-00000000"
    bus_id: str = "0000:00:00.0"
    driver_version: str = "Unknown"
    cuda_version: str = "Unknown"
    vbios_version: str = "Unknown"
    vram_total_mib: float = 12288.0
    power_default_limit_w: float = 170.0
    power_max_limit_w: float = 170.0
    clock_max_gfx_mhz: int = 2130
    clock_max_sm_mhz: int = 2130
    clock_max_mem_mhz: int = 7501
    pcie_max_gen: int = 4
    pcie_max_width: int = 16
    temp_slowdown_c: int = 90
    temp_shutdown_c: int = 95
    backend: str = "NVML"


@dataclass
class GpuSnapshot:
    """A single timestamped telemetry snapshot for an NVIDIA GPU."""
    timestamp: float = field(default_factory=time.time)
    gpu_index: int = 0
    gpu_name: str = "NVIDIA GPU"
    pstate: str = "P0"

    # Core & memory controller utilization (%)
    gpu_util: float = 0.0
    mem_ctrl_util: float = 0.0

    # VRAM metrics (MiB & %)
    vram_used_mib: float = 0.0
    vram_free_mib: float = 0.0
    vram_total_mib: float = 12288.0
    vram_pct: float = 0.0

    # Thermal & cooling
    temp_c: float = 0.0
    fan_pct: float = 0.0

    # Power metrics (Watts & %)
    power_draw_w: float = 0.0
    power_limit_w: float = 170.0
    power_pct: float = 0.0

    # Clocks (MHz & %)
    clock_gfx_mhz: int = 0
    clock_max_gfx_mhz: int = 2130
    clock_sm_mhz: int = 0
    clock_mem_mhz: int = 0
    clock_max_mem_mhz: int = 7501
    clock_gfx_pct: float = 0.0
    clock_mem_pct: float = 0.0

    # PCIe link & bandwidth
    pcie_gen: int = 4
    pcie_max_gen: int = 4
    pcie_width: int = 16
    pcie_max_width: int = 16
    pcie_tx_mbs: float = 0.0
    pcie_rx_mbs: float = 0.0

    # Video engines (%)
    enc_util: float = 0.0
    dec_util: float = 0.0

    # Active GPU processes
    processes: List[GpuProcess] = field(default_factory=list)


# Metric channel metadata used by graphs, legends, and statistics tables
METRIC_CHANNELS: Dict[str, Dict[str, object]] = {
    "gpu_util": {
        "label": "GPU Core Load",
        "short": "GPU",
        "unit": "%",
        "color_hex": "#00f0ff",
        "rgb": (0.0, 0.941, 1.0),
        "max_val": 100.0,
        "format": "{:.1f}%",
    },
    "vram_pct": {
        "label": "VRAM Allocation",
        "short": "VRAM",
        "unit": "%",
        "color_hex": "#10b981",
        "rgb": (0.063, 0.725, 0.506),
        "max_val": 100.0,
        "format": "{:.1f}%",
    },
    "mem_ctrl_util": {
        "label": "Mem Controller",
        "short": "MEMBUS",
        "unit": "%",
        "color_hex": "#38bdf8",
        "rgb": (0.220, 0.741, 0.973),
        "max_val": 100.0,
        "format": "{:.1f}%",
    },
    "temp_c": {
        "label": "GPU Temperature",
        "short": "TEMP",
        "unit": "°C",
        "color_hex": "#f59e0b",
        "rgb": (0.961, 0.620, 0.043),
        "max_val": 100.0,
        "format": "{:.0f}°C",
    },
    "power_pct": {
        "label": "Power Draw",
        "short": "PWR",
        "unit": "%",
        "color_hex": "#a855f7",
        "rgb": (0.659, 0.333, 0.969),
        "max_val": 100.0,
        "format": "{:.1f}%",
    },
    "fan_pct": {
        "label": "Cooling Fan",
        "short": "FAN",
        "unit": "%",
        "color_hex": "#fb7185",
        "rgb": (0.984, 0.443, 0.522),
        "max_val": 100.0,
        "format": "{:.0f}%",
    },
    "clock_gfx_pct": {
        "label": "Core Clock",
        "short": "CLK",
        "unit": "%",
        "color_hex": "#60a5fa",
        "rgb": (0.376, 0.647, 0.980),
        "max_val": 100.0,
        "format": "{:.1f}%",
    },
    "pcie_total_mbs": {
        "label": "PCIe Bandwidth",
        "short": "PCIe",
        "unit": "MB/s",
        "color_hex": "#34d399",
        "rgb": (0.204, 0.827, 0.600),
        "max_val": 1000.0,  # Dynamically scaled
        "format": "{:.1f} MB/s",
    },
}


class GpuHistoryBuffer:
    """Rolling time-series store for GPU telemetry snapshots with statistical summaries."""

    def __init__(self, max_points: int = 240):
        self.max_points = max(30, int(max_points))
        self.snapshots: deque[GpuSnapshot] = deque(maxlen=self.max_points)

    def set_max_points(self, max_points: int):
        new_max = max(30, int(max_points))
        if new_max != self.max_points:
            self.max_points = new_max
            self.snapshots = deque(self.snapshots, maxlen=self.max_points)

    def push(self, snap: GpuSnapshot):
        self.snapshots.append(snap)

    def clear(self):
        self.snapshots.clear()

    def latest(self) -> Optional[GpuSnapshot]:
        return self.snapshots[-1] if self.snapshots else None

    def extract_value(self, snap: GpuSnapshot, key: str) -> float:
        if key == "pcie_total_mbs":
            return snap.pcie_tx_mbs + snap.pcie_rx_mbs
        return float(getattr(snap, key, 0.0))

    def get_raw_series(self, key: str, count: Optional[int] = None) -> List[float]:
        n = count or self.max_points
        snaps = list(self.snapshots)[-n:]
        vals = [self.extract_value(s, key) for s in snaps]
        if len(vals) < n:
            vals = [0.0] * (n - len(vals)) + vals
        return vals

    def get_normalized_series(self, key: str, count: Optional[int] = None, dynamic_max: Optional[float] = None) -> List[float]:
        raw = self.get_raw_series(key, count=count)
        if dynamic_max is not None and dynamic_max > 0:
            ceil = dynamic_max
        elif key == "pcie_total_mbs":
            peak = max(raw) if raw else 10.0
            ceil = max(50.0, peak * 1.2)
        else:
            meta = METRIC_CHANNELS.get(key, {})
            ceil = float(meta.get("max_val", 100.0))
        return [max(0.0, min(1.0, v / ceil)) for v in raw]

    def get_channel_stats(self, key: str) -> Dict[str, float]:
        if not self.snapshots:
            return {"current": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0}
        vals = [self.extract_value(s, key) for s in self.snapshots]
        return {
            "current": vals[-1],
            "min": min(vals),
            "max": max(vals),
            "avg": sum(vals) / len(vals),
        }

    def export_csv(self, filepath: str):
        snaps = list(self.snapshots)
        fieldnames = [
            "timestamp", "gpu_index", "gpu_name", "pstate",
            "gpu_util", "mem_ctrl_util", "vram_used_mib", "vram_total_mib", "vram_pct",
            "temp_c", "fan_pct", "power_draw_w", "power_limit_w", "power_pct",
            "clock_gfx_mhz", "clock_mem_mhz", "pcie_tx_mbs", "pcie_rx_mbs",
            "enc_util", "dec_util", "process_count"
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in snaps:
                writer.writerow({
                    "timestamp": f"{s.timestamp:.3f}",
                    "gpu_index": s.gpu_index,
                    "gpu_name": s.gpu_name,
                    "pstate": s.pstate,
                    "gpu_util": f"{s.gpu_util:.1f}",
                    "mem_ctrl_util": f"{s.mem_ctrl_util:.1f}",
                    "vram_used_mib": f"{s.vram_used_mib:.1f}",
                    "vram_total_mib": f"{s.vram_total_mib:.1f}",
                    "vram_pct": f"{s.vram_pct:.2f}",
                    "temp_c": f"{s.temp_c:.1f}",
                    "fan_pct": f"{s.fan_pct:.1f}",
                    "power_draw_w": f"{s.power_draw_w:.2f}",
                    "power_limit_w": f"{s.power_limit_w:.2f}",
                    "power_pct": f"{s.power_pct:.2f}",
                    "clock_gfx_mhz": s.clock_gfx_mhz,
                    "clock_mem_mhz": s.clock_mem_mhz,
                    "pcie_tx_mbs": f"{s.pcie_tx_mbs:.2f}",
                    "pcie_rx_mbs": f"{s.pcie_rx_mbs:.2f}",
                    "enc_util": f"{s.enc_util:.1f}",
                    "dec_util": f"{s.dec_util:.1f}",
                    "process_count": len(s.processes),
                })

    def export_json(self, filepath: str):
        data = [asdict(s) for s in self.snapshots]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


class NvidiaTelemetryEngine:
    """
    Collects NVIDIA GPU telemetry using direct libnvidia-ml.so.1 ctypes bindings,
    with seamless fallback to nvidia-smi CLI or synthetic simulation.
    """

    def __init__(self):
        self._nvml = None
        self._handles: List[ctypes.c_void_p] = []
        self.specs: List[GpuDeviceSpec] = []
        self.backend: str = "NONE"
        self._sim_phase: float = 0.0
        self._uid_cache: Dict[int, str] = {}
        self._init_backend()

    def _init_backend(self):
        # 1. Try direct NVML shared library via ctypes
        for libname in ("libnvidia-ml.so.1", "libnvidia-ml.so"):
            try:
                lib = ctypes.CDLL(libname)
                if lib.nvmlInit_v2() == 0:
                    count = ctypes.c_uint(0)
                    if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0 and count.value > 0:
                        self._nvml = lib
                        self.backend = "NVML"
                        self._discover_nvml_devices(count.value)
                        return
            except Exception:
                pass

        # 2. Fallback to nvidia-smi CLI if present
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,uuid,pci.bus_id,driver_version,vbios_version,memory.total,power.default_limit,power.max_limit,clocks.max.graphics,clocks.max.sm,clocks.max.memory,pcie.link.gen.max,pcie.link.width.max",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                self.backend = "NVIDIA-SMI"
                for line in res.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 14:
                        self.specs.append(
                            GpuDeviceSpec(
                                index=self._safe_int(parts[0], 0),
                                name=parts[1] or "NVIDIA GPU",
                                uuid=parts[2] or "GPU-0",
                                bus_id=parts[3] or "0000:00:00.0",
                                driver_version=parts[4] or "Unknown",
                                cuda_version="12.x+",
                                vbios_version=parts[5] or "Unknown",
                                vram_total_mib=self._safe_float(parts[6], 12288.0),
                                power_default_limit_w=self._safe_float(parts[7], 170.0),
                                power_max_limit_w=self._safe_float(parts[8], 170.0),
                                clock_max_gfx_mhz=self._safe_int(parts[9], 2100),
                                clock_max_sm_mhz=self._safe_int(parts[10], 2100),
                                clock_max_mem_mhz=self._safe_int(parts[11], 7500),
                                pcie_max_gen=self._safe_int(parts[12], 4),
                                pcie_max_width=self._safe_int(parts[13], 16),
                                backend="NVIDIA-SMI",
                            )
                        )
                if self.specs:
                    return
        except Exception:
            pass

        # 3. Fallback to synthetic simulator mode
        self.backend = "SIMULATOR"
        self.specs = [
            GpuDeviceSpec(
                index=0,
                name="NVIDIA GeForce RTX 3060 (Simulated)",
                uuid="GPU-SIM-RTX3060",
                bus_id="0000:2D:00.0",
                driver_version="595.99.02",
                cuda_version="13.2",
                vbios_version="94.06.2F.00.F5",
                vram_total_mib=12288.0,
                power_default_limit_w=170.0,
                power_max_limit_w=170.0,
                clock_max_gfx_mhz=2130,
                clock_max_sm_mhz=2130,
                clock_max_mem_mhz=7501,
                pcie_max_gen=4,
                pcie_max_width=16,
                backend="SIMULATOR",
            )
        ]

    def _discover_nvml_devices(self, count: int):
        lib = self._nvml
        buf = ctypes.create_string_buffer(128)

        driver_ver = "Unknown"
        if lib.nvmlSystemGetDriverVersion(buf, 128) == 0:
            driver_ver = buf.value.decode("utf-8", errors="replace")

        cuda_str = "Unknown"
        cuda_int = ctypes.c_int(0)
        if hasattr(lib, "nvmlSystemGetCudaDriverVersion_v2") and lib.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(cuda_int)) == 0:
            cuda_str = f"{cuda_int.value // 1000}.{(cuda_int.value % 1000) // 10}"

        for idx in range(count):
            handle = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(idx, ctypes.byref(handle)) != 0:
                continue
            self._handles.append(handle)

            name = f"NVIDIA GPU {idx}"
            if lib.nvmlDeviceGetName(handle, buf, 128) == 0:
                name = buf.value.decode("utf-8", errors="replace")

            uuid = f"GPU-{idx}"
            if lib.nvmlDeviceGetUUID(handle, buf, 128) == 0:
                uuid = buf.value.decode("utf-8", errors="replace")

            vbios = "Unknown"
            if lib.nvmlDeviceGetVbiosVersion(handle, buf, 128) == 0:
                vbios = buf.value.decode("utf-8", errors="replace")

            pci = _NvmlPciInfo()
            bus_id = "0000:00:00.0"
            if lib.nvmlDeviceGetPciInfo_v3(handle, ctypes.byref(pci)) == 0:
                bus_id = pci.busId.decode("utf-8", errors="replace")

            mem = _NvmlMemory()
            vram_total_mib = 12288.0
            if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
                vram_total_mib = mem.total / (1024.0 * 1024.0)

            pwr_lim = ctypes.c_uint(170000)
            lib.nvmlDeviceGetPowerManagementLimit(handle, ctypes.byref(pwr_lim))
            pwr_def = ctypes.c_uint(pwr_lim.value)
            if hasattr(lib, "nvmlDeviceGetPowerManagementDefaultLimit"):
                lib.nvmlDeviceGetPowerManagementDefaultLimit(handle, ctypes.byref(pwr_def))

            max_gfx = ctypes.c_uint(2100)
            max_sm = ctypes.c_uint(2100)
            max_mem = ctypes.c_uint(7500)
            lib.nvmlDeviceGetMaxClockInfo(handle, 0, ctypes.byref(max_gfx))
            lib.nvmlDeviceGetMaxClockInfo(handle, 1, ctypes.byref(max_sm))
            lib.nvmlDeviceGetMaxClockInfo(handle, 2, ctypes.byref(max_mem))

            max_gen = ctypes.c_uint(4)
            max_width = ctypes.c_uint(16)
            lib.nvmlDeviceGetMaxPcieLinkGeneration(handle, ctypes.byref(max_gen))
            lib.nvmlDeviceGetMaxPcieLinkWidth(handle, ctypes.byref(max_width))

            slow_temp = ctypes.c_uint(90)
            shut_temp = ctypes.c_uint(95)
            if hasattr(lib, "nvmlDeviceGetTemperatureThreshold"):
                lib.nvmlDeviceGetTemperatureThreshold(handle, 1, ctypes.byref(slow_temp))
                lib.nvmlDeviceGetTemperatureThreshold(handle, 0, ctypes.byref(shut_temp))

            self.specs.append(
                GpuDeviceSpec(
                    index=idx,
                    name=name,
                    uuid=uuid,
                    bus_id=bus_id,
                    driver_version=driver_ver,
                    cuda_version=cuda_str,
                    vbios_version=vbios,
                    vram_total_mib=round(vram_total_mib, 1),
                    power_default_limit_w=round(pwr_def.value / 1000.0, 1),
                    power_max_limit_w=round(pwr_lim.value / 1000.0, 1),
                    clock_max_gfx_mhz=max_gfx.value or 2100,
                    clock_max_sm_mhz=max_sm.value or 2100,
                    clock_max_mem_mhz=max_mem.value or 7500,
                    pcie_max_gen=max_gen.value or 4,
                    pcie_max_width=max_width.value or 16,
                    temp_slowdown_c=slow_temp.value or 90,
                    temp_shutdown_c=shut_temp.value or 95,
                    backend="NVML",
                )
            )

    def get_device_count(self) -> int:
        return len(self.specs)

    def get_device_spec(self, gpu_index: int = 0) -> GpuDeviceSpec:
        if 0 <= gpu_index < len(self.specs):
            return self.specs[gpu_index]
        return self.specs[0]

    def poll(self, gpu_index: int = 0, include_processes: bool = True) -> GpuSnapshot:
        if self.backend == "NVML" and 0 <= gpu_index < len(self._handles):
            return self._poll_nvml(gpu_index, include_processes=include_processes)
        if self.backend == "NVIDIA-SMI":
            return self._poll_nvidia_smi(gpu_index, include_processes=include_processes)
        return self._poll_simulator(gpu_index)

    def _poll_nvml(self, gpu_index: int, include_processes: bool = True) -> GpuSnapshot:
        lib = self._nvml
        handle = self._handles[gpu_index]
        spec = self.specs[gpu_index]

        util = _NvmlUtilization()
        gpu_u = 0.0
        mem_u = 0.0
        if lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == 0:
            gpu_u = float(util.gpu)
            mem_u = float(util.memory)

        mem = _NvmlMemory()
        vram_used = 0.0
        vram_free = 0.0
        vram_total = spec.vram_total_mib
        if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
            vram_used = mem.used / (1024.0 * 1024.0)
            vram_free = mem.free / (1024.0 * 1024.0)
            vram_total = max(1.0, mem.total / (1024.0 * 1024.0))
        vram_pct = (vram_used / vram_total) * 100.0 if vram_total > 0 else 0.0

        temp = ctypes.c_uint(0)
        lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp))

        fan = ctypes.c_uint(0)
        lib.nvmlDeviceGetFanSpeed(handle, ctypes.byref(fan))

        pwr = ctypes.c_uint(0)
        pwr_lim = ctypes.c_uint(int(spec.power_max_limit_w * 1000))
        lib.nvmlDeviceGetPowerUsage(handle, ctypes.byref(pwr))
        lib.nvmlDeviceGetPowerManagementLimit(handle, ctypes.byref(pwr_lim))
        power_draw_w = pwr.value / 1000.0
        power_limit_w = max(1.0, pwr_lim.value / 1000.0)
        power_pct = min(100.0, (power_draw_w / power_limit_w) * 100.0)

        clk_gfx = ctypes.c_uint(0)
        clk_sm = ctypes.c_uint(0)
        clk_mem = ctypes.c_uint(0)
        lib.nvmlDeviceGetClockInfo(handle, 0, ctypes.byref(clk_gfx))
        lib.nvmlDeviceGetClockInfo(handle, 1, ctypes.byref(clk_sm))
        lib.nvmlDeviceGetClockInfo(handle, 2, ctypes.byref(clk_mem))

        clock_gfx_pct = min(100.0, (clk_gfx.value / max(1, spec.clock_max_gfx_mhz)) * 100.0)
        clock_mem_pct = min(100.0, (clk_mem.value / max(1, spec.clock_max_mem_mhz)) * 100.0)

        pcie_gen = ctypes.c_uint(spec.pcie_max_gen)
        pcie_width = ctypes.c_uint(spec.pcie_max_width)
        lib.nvmlDeviceGetCurrPcieLinkGeneration(handle, ctypes.byref(pcie_gen))
        lib.nvmlDeviceGetCurrPcieLinkWidth(handle, ctypes.byref(pcie_width))

        tx_kb = ctypes.c_uint(0)
        rx_kb = ctypes.c_uint(0)
        lib.nvmlDeviceGetPcieThroughput(handle, 0, ctypes.byref(tx_kb))
        lib.nvmlDeviceGetPcieThroughput(handle, 1, ctypes.byref(rx_kb))
        pcie_tx_mbs = tx_kb.value / 1024.0
        pcie_rx_mbs = rx_kb.value / 1024.0

        enc_u = ctypes.c_uint(0)
        enc_s = ctypes.c_uint(0)
        dec_u = ctypes.c_uint(0)
        dec_s = ctypes.c_uint(0)
        lib.nvmlDeviceGetEncoderUtilization(handle, ctypes.byref(enc_u), ctypes.byref(enc_s))
        lib.nvmlDeviceGetDecoderUtilization(handle, ctypes.byref(dec_u), ctypes.byref(dec_s))

        pstate = ctypes.c_uint(0)
        lib.nvmlDeviceGetPerformanceState(handle, ctypes.byref(pstate))
        pstate_str = f"P{pstate.value}"

        processes = self._get_nvml_processes(handle, vram_total) if include_processes else []

        return GpuSnapshot(
            timestamp=time.time(),
            gpu_index=gpu_index,
            gpu_name=spec.name,
            pstate=pstate_str,
            gpu_util=gpu_u,
            mem_ctrl_util=mem_u,
            vram_used_mib=vram_used,
            vram_free_mib=vram_free,
            vram_total_mib=vram_total,
            vram_pct=vram_pct,
            temp_c=float(temp.value),
            fan_pct=float(fan.value),
            power_draw_w=power_draw_w,
            power_limit_w=power_limit_w,
            power_pct=power_pct,
            clock_gfx_mhz=int(clk_gfx.value),
            clock_max_gfx_mhz=spec.clock_max_gfx_mhz,
            clock_sm_mhz=int(clk_sm.value),
            clock_mem_mhz=int(clk_mem.value),
            clock_max_mem_mhz=spec.clock_max_mem_mhz,
            clock_gfx_pct=clock_gfx_pct,
            clock_mem_pct=clock_mem_pct,
            pcie_gen=int(pcie_gen.value),
            pcie_max_gen=spec.pcie_max_gen,
            pcie_width=int(pcie_width.value),
            pcie_max_width=spec.pcie_max_width,
            pcie_tx_mbs=pcie_tx_mbs,
            pcie_rx_mbs=pcie_rx_mbs,
            enc_util=float(enc_u.value),
            dec_util=float(dec_u.value),
            processes=processes,
        )

    def _get_nvml_processes(self, handle: ctypes.c_void_p, vram_total_mib: float) -> List[GpuProcess]:
        lib = self._nvml
        proc_map: Dict[int, Dict[str, object]] = {}

        def _query_list(fn_v2: str, fn_v1: str, tag: str):
            if hasattr(lib, fn_v2):
                fn = getattr(lib, fn_v2)
                cnt = ctypes.c_uint(128)
                arr = (_NvmlProcessInfoV2 * 128)()
                if fn(handle, ctypes.byref(cnt), arr) == 0:
                    for i in range(cnt.value):
                        pid = int(arr[i].pid)
                        raw_mem = arr[i].usedGpuMemory
                        mib = 0.0 if raw_mem > (1 << 50) else raw_mem / (1024.0 * 1024.0)
                        self._merge_proc(proc_map, pid, tag, mib)
                    return
            if hasattr(lib, fn_v1):
                fn = getattr(lib, fn_v1)
                cnt = ctypes.c_uint(128)
                arr = (_NvmlProcessInfoV1 * 128)()
                if fn(handle, ctypes.byref(cnt), arr) == 0:
                    for i in range(cnt.value):
                        pid = int(arr[i].pid)
                        raw_mem = arr[i].usedGpuMemory
                        mib = 0.0 if raw_mem > (1 << 50) else raw_mem / (1024.0 * 1024.0)
                        self._merge_proc(proc_map, pid, tag, mib)

        _query_list(
            "nvmlDeviceGetGraphicsRunningProcesses_v2",
            "nvmlDeviceGetGraphicsRunningProcesses",
            "G",
        )
        _query_list(
            "nvmlDeviceGetComputeRunningProcesses_v2",
            "nvmlDeviceGetComputeRunningProcesses",
            "C",
        )

        result: List[GpuProcess] = []
        for pid, info in proc_map.items():
            name, cmdline, user = self._inspect_pid(pid)
            vram_mib = float(info["vram_mib"])
            vram_pct = (vram_mib / max(1.0, vram_total_mib)) * 100.0
            result.append(
                GpuProcess(
                    pid=pid,
                    proc_type=str(info["type"]),
                    name=name,
                    cmdline=cmdline,
                    user=user,
                    vram_mib=round(vram_mib, 1),
                    vram_pct=round(vram_pct, 2),
                )
            )
        result.sort(key=lambda p: (p.vram_mib, p.pid), reverse=True)
        return result

    @staticmethod
    def _merge_proc(proc_map: Dict[int, Dict[str, object]], pid: int, tag: str, mib: float):
        if pid not in proc_map:
            proc_map[pid] = {"type": tag, "vram_mib": mib}
        else:
            existing_type = str(proc_map[pid]["type"])
            if tag not in existing_type:
                proc_map[pid]["type"] = "C+G"
            proc_map[pid]["vram_mib"] = max(float(proc_map[pid]["vram_mib"]), mib)

    def _inspect_pid(self, pid: int) -> Tuple[str, str, str]:
        proc_dir = f"/proc/{pid}"
        name = f"pid-{pid}"
        cmdline = ""
        user = "user"
        try:
            st = os.stat(proc_dir)
            uid = st.st_uid
            if uid not in self._uid_cache:
                try:
                    self._uid_cache[uid] = pwd.getpwuid(uid).pw_name
                except Exception:
                    self._uid_cache[uid] = str(uid)
            user = self._uid_cache[uid]
        except Exception:
            pass

        try:
            with open(f"{proc_dir}/comm", "r", encoding="utf-8", errors="replace") as f:
                name = f.read().strip() or name
        except Exception:
            pass

        try:
            with open(f"{proc_dir}/cmdline", "rb") as f:
                raw = f.read(512)
                if raw:
                    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
                    if parts:
                        exe_base = os.path.basename(parts[0])
                        if exe_base:
                            name = exe_base
                        cmdline = " ".join(parts)
        except Exception:
            pass

        if not cmdline:
            cmdline = name
        return name, cmdline, user

    def _poll_nvidia_smi(self, gpu_index: int, include_processes: bool = True) -> GpuSnapshot:
        spec = self.get_device_spec(gpu_index)
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    f"--id={gpu_index}",
                    "--query-gpu=pstate,utilization.gpu,utilization.memory,memory.used,memory.free,memory.total,temperature.gpu,fan.speed,power.draw,power.limit,clocks.current.graphics,clocks.current.sm,clocks.current.memory,pcie.link.gen.current,pcie.link.width.current",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
                pstate = parts[0] if len(parts) > 0 else "P0"
                gpu_u = self._safe_float(parts[1], 0.0) if len(parts) > 1 else 0.0
                mem_u = self._safe_float(parts[2], 0.0) if len(parts) > 2 else 0.0
                v_used = self._safe_float(parts[3], 0.0) if len(parts) > 3 else 0.0
                v_free = self._safe_float(parts[4], 0.0) if len(parts) > 4 else 0.0
                v_tot = max(1.0, self._safe_float(parts[5], spec.vram_total_mib)) if len(parts) > 5 else spec.vram_total_mib
                temp = self._safe_float(parts[6], 0.0) if len(parts) > 6 else 0.0
                fan = self._safe_float(parts[7], 0.0) if len(parts) > 7 else 0.0
                pwr = self._safe_float(parts[8], 0.0) if len(parts) > 8 else 0.0
                pwr_lim = max(1.0, self._safe_float(parts[9], spec.power_max_limit_w)) if len(parts) > 9 else spec.power_max_limit_w
                clk_g = self._safe_int(parts[10], 0) if len(parts) > 10 else 0
                clk_sm = self._safe_int(parts[11], 0) if len(parts) > 11 else 0
                clk_m = self._safe_int(parts[12], 0) if len(parts) > 12 else 0
                p_gen = self._safe_int(parts[13], spec.pcie_max_gen) if len(parts) > 13 else spec.pcie_max_gen
                p_wid = self._safe_int(parts[14], spec.pcie_max_width) if len(parts) > 14 else spec.pcie_max_width

                return GpuSnapshot(
                    timestamp=time.time(),
                    gpu_index=gpu_index,
                    gpu_name=spec.name,
                    pstate=pstate,
                    gpu_util=gpu_u,
                    mem_ctrl_util=mem_u,
                    vram_used_mib=v_used,
                    vram_free_mib=v_free,
                    vram_total_mib=v_tot,
                    vram_pct=(v_used / v_tot) * 100.0,
                    temp_c=temp,
                    fan_pct=fan,
                    power_draw_w=pwr,
                    power_limit_w=pwr_lim,
                    power_pct=min(100.0, (pwr / pwr_lim) * 100.0),
                    clock_gfx_mhz=clk_g,
                    clock_max_gfx_mhz=spec.clock_max_gfx_mhz,
                    clock_sm_mhz=clk_sm,
                    clock_mem_mhz=clk_m,
                    clock_max_mem_mhz=spec.clock_max_mem_mhz,
                    clock_gfx_pct=min(100.0, (clk_g / max(1, spec.clock_max_gfx_mhz)) * 100.0),
                    clock_mem_pct=min(100.0, (clk_m / max(1, spec.clock_max_mem_mhz)) * 100.0),
                    pcie_gen=p_gen,
                    pcie_max_gen=spec.pcie_max_gen,
                    pcie_width=p_wid,
                    pcie_max_width=spec.pcie_max_width,
                    processes=[],
                )
        except Exception:
            pass
        return self._poll_simulator(gpu_index)

    def _poll_simulator(self, gpu_index: int) -> GpuSnapshot:
        spec = self.get_device_spec(gpu_index)
        self._sim_phase += 0.25
        p = self._sim_phase
        gpu_u = max(3.0, min(98.0, 35.0 + 25.0 * math.sin(p) + 12.0 * math.cos(p * 2.3)))
        mem_u = max(2.0, min(90.0, gpu_u * 0.55 + 8.0 * math.sin(p * 1.4)))
        v_used = 1850.0 + 420.0 * math.sin(p * 0.4)
        v_tot = spec.vram_total_mib
        temp = 52.0 + (gpu_u * 0.22)
        fan = 0.0 if temp < 55.0 else min(100.0, (temp - 50.0) * 1.8)
        pwr = 28.0 + (gpu_u / 100.0) * (spec.power_max_limit_w - 35.0)
        clk_g = int(600 + (gpu_u / 100.0) * (spec.clock_max_gfx_mhz - 600))
        clk_m = 5001 if gpu_u < 25 else 7501
        return GpuSnapshot(
            timestamp=time.time(),
            gpu_index=gpu_index,
            gpu_name=spec.name,
            pstate="P0" if gpu_u > 25 else "P5",
            gpu_util=round(gpu_u, 1),
            mem_ctrl_util=round(mem_u, 1),
            vram_used_mib=round(v_used, 1),
            vram_free_mib=round(v_tot - v_used, 1),
            vram_total_mib=v_tot,
            vram_pct=round((v_used / v_tot) * 100.0, 2),
            temp_c=round(temp, 1),
            fan_pct=round(fan, 1),
            power_draw_w=round(pwr, 2),
            power_limit_w=spec.power_max_limit_w,
            power_pct=round((pwr / spec.power_max_limit_w) * 100.0, 1),
            clock_gfx_mhz=clk_g,
            clock_max_gfx_mhz=spec.clock_max_gfx_mhz,
            clock_sm_mhz=clk_g,
            clock_mem_mhz=clk_m,
            clock_max_mem_mhz=spec.clock_max_mem_mhz,
            clock_gfx_pct=round((clk_g / spec.clock_max_gfx_mhz) * 100.0, 1),
            clock_mem_pct=round((clk_m / spec.clock_max_mem_mhz) * 100.0, 1),
            pcie_gen=4,
            pcie_max_gen=4,
            pcie_width=16,
            pcie_max_width=16,
            pcie_tx_mbs=round(14.0 + 30.0 * abs(math.sin(p)), 1),
            pcie_rx_mbs=round(48.0 + 85.0 * abs(math.cos(p)), 1),
            enc_util=0.0,
            dec_util=0.0,
            processes=[],
        )

    @staticmethod
    def _safe_float(val: str, default: float = 0.0) -> float:
        try:
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _safe_int(val: str, default: int = 0) -> int:
        try:
            return int(float(val))
        except Exception:
            return default

    def shutdown(self):
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml = None
