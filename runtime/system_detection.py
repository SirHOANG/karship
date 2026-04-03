from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


@dataclass(slots=True)
class HardwareProfile:
    os_name: str
    cpu_physical_cores: int
    cpu_logical_cores: int
    cpu_usage_percent: float
    total_ram_gb: float
    available_ram_gb: float
    gpu_name: str | None
    gpu_present: bool
    tier: str
    recommended_mode: str
    recommended_concurrency: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name,
            "cpu_physical_cores": self.cpu_physical_cores,
            "cpu_logical_cores": self.cpu_logical_cores,
            "cpu_usage_percent": round(self.cpu_usage_percent, 2),
            "total_ram_gb": round(self.total_ram_gb, 2),
            "available_ram_gb": round(self.available_ram_gb, 2),
            "gpu_name": self.gpu_name,
            "gpu_present": self.gpu_present,
            "tier": self.tier,
            "recommended_mode": self.recommended_mode,
            "recommended_concurrency": self.recommended_concurrency,
        }


class SystemDetector:
    def __init__(self) -> None:
        try:
            import psutil  # type: ignore
        except Exception:
            psutil = None
        self._psutil = psutil

    def detect(self) -> HardwareProfile:
        total_ram_gb, available_ram_gb = self._detect_memory()
        physical, logical = self._detect_cpu_cores()
        cpu_usage = self._detect_cpu_usage()
        gpu = self._detect_gpu_name()
        tier = self._classify_tier(total_ram_gb)
        mode = self._tier_to_mode(tier)
        concurrency = self._recommended_concurrency(tier, logical)
        return HardwareProfile(
            os_name=platform.platform(),
            cpu_physical_cores=physical,
            cpu_logical_cores=logical,
            cpu_usage_percent=cpu_usage,
            total_ram_gb=total_ram_gb,
            available_ram_gb=available_ram_gb,
            gpu_name=gpu,
            gpu_present=gpu is not None,
            tier=tier,
            recommended_mode=mode,
            recommended_concurrency=concurrency,
        )

    def _detect_memory(self) -> tuple[float, float]:
        if self._psutil is not None:
            vm = self._psutil.virtual_memory()
            return vm.total / (1024**3), vm.available / (1024**3)

        # Fallback using os.sysconf when available.
        if hasattr(os, "sysconf"):
            pages = _safe_int(os.sysconf("SC_PHYS_PAGES"), 0)
            page_size = _safe_int(os.sysconf("SC_PAGE_SIZE"), 0)
            if pages > 0 and page_size > 0:
                total = pages * page_size
                # No reliable available memory fallback without psutil.
                return total / (1024**3), total / (1024**3)

        # Conservative fallback.
        return 8.0, 8.0

    def _detect_cpu_cores(self) -> tuple[int, int]:
        if self._psutil is not None:
            physical = self._psutil.cpu_count(logical=False) or 1
            logical = self._psutil.cpu_count(logical=True) or physical
            return int(physical), int(logical)

        logical = os.cpu_count() or 1
        return max(1, logical // 2), logical

    def _detect_cpu_usage(self) -> float:
        if self._psutil is not None:
            return _safe_float(self._psutil.cpu_percent(interval=0.1), 0.0)

        # Basic fallback: load average ratio on unix, else 0.
        if hasattr(os, "getloadavg"):
            load1, *_ = os.getloadavg()
            cores = max(os.cpu_count() or 1, 1)
            return min(100.0, (load1 / cores) * 100.0)
        return 0.0

    def _detect_gpu_name(self) -> str | None:
        system = platform.system().lower()
        if "windows" in system:
            return self._detect_gpu_windows()
        if "linux" in system:
            return self._detect_gpu_linux()
        if "darwin" in system:
            return self._detect_gpu_macos()
        return None

    def _detect_gpu_windows(self) -> str | None:
        candidates = [
            ["wmic", "path", "win32_VideoController", "get", "name"],
            ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
        ]
        for cmd in candidates:
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=3)
                lines = [line.strip() for line in out.splitlines() if line.strip()]
                lines = [line for line in lines if line.lower() not in {"name"}]
                if lines:
                    return lines[0]
            except Exception:
                continue
        return None

    def _detect_gpu_linux(self) -> str | None:
        try:
            out = subprocess.check_output(
                ["lspci"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            for line in out.splitlines():
                lower = line.lower()
                if "vga" in lower or "3d controller" in lower:
                    return line.strip()
        except Exception:
            return None
        return None

    def _detect_gpu_macos(self) -> str | None:
        try:
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Chipset Model:"):
                    return line.split(":", maxsplit=1)[1].strip()
        except Exception:
            return None
        return None

    def _classify_tier(self, total_ram_gb: float) -> str:
        # LOW: 4/8 GB, MID: 12/16 GB, HIGH: 16/32+ GB.
        if total_ram_gb <= 8.5:
            return "low"
        if total_ram_gb <= 16.5:
            return "mid"
        return "high"

    def _tier_to_mode(self, tier: str) -> str:
        if tier == "low":
            return "eco"
        if tier == "mid":
            return "balanced"
        return "turbo"

    def _recommended_concurrency(self, tier: str, logical_cores: int) -> int:
        if tier == "low":
            return 1
        if tier == "mid":
            return max(2, min(4, logical_cores // 2 or 1))
        return max(4, min(8, logical_cores))
