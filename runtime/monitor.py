from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RuntimeLimits:
    soft_process_mem_mb: float
    hard_process_mem_mb: float
    cpu_soft_limit_percent: float
    throttle_sleep_ms: int
    check_every_ops: int


class RuntimeMonitor:
    def __init__(
        self,
        *,
        execution_mode: str,
        tier: str,
        strict_safety: bool,
        process_probe: callable | None = None,
    ) -> None:
        self.execution_mode = execution_mode
        self.tier = tier
        self.strict_safety = strict_safety
        self.operations = 0
        self.peak_process_mem_mb = 0.0
        self.last_cpu_percent = 0.0
        self.warnings: list[str] = []
        self._process_probe = process_probe or self._default_process_probe
        self.limits = self._compute_limits()

    def _compute_limits(self) -> RuntimeLimits:
        if self.tier == "low":
            return RuntimeLimits(
                soft_process_mem_mb=300,
                hard_process_mem_mb=500,
                cpu_soft_limit_percent=78.0,
                throttle_sleep_ms=5,
                check_every_ops=75,
            )
        if self.tier == "mid":
            return RuntimeLimits(
                soft_process_mem_mb=900,
                hard_process_mem_mb=1400,
                cpu_soft_limit_percent=85.0,
                throttle_sleep_ms=3,
                check_every_ops=120,
            )
        return RuntimeLimits(
            soft_process_mem_mb=2200,
            hard_process_mem_mb=3600,
            cpu_soft_limit_percent=92.0,
            throttle_sleep_ms=1,
            check_every_ops=180,
        )

    def tick(self) -> dict[str, Any]:
        self.operations += 1
        if self.operations % self.limits.check_every_ops != 0:
            return {"throttled": False, "warnings": []}
        return self.check_usage()

    def check_usage(self) -> dict[str, Any]:
        stats = self._process_probe()
        mem_mb = float(stats.get("mem_mb", 0.0))
        cpu_percent = float(stats.get("cpu_percent", 0.0))
        self.peak_process_mem_mb = max(self.peak_process_mem_mb, mem_mb)
        self.last_cpu_percent = cpu_percent

        warnings: list[str] = []
        throttled = False

        if mem_mb >= self.limits.soft_process_mem_mb:
            warnings.append(
                f"Process memory high ({mem_mb:.1f} MB / soft {self.limits.soft_process_mem_mb:.1f} MB)."
            )
        if mem_mb >= self.limits.hard_process_mem_mb and self.strict_safety:
            warnings.append(
                f"Process memory exceeded hard limit ({mem_mb:.1f} MB)."
            )
        if cpu_percent >= self.limits.cpu_soft_limit_percent:
            warnings.append(
                f"CPU usage high ({cpu_percent:.1f}% >= {self.limits.cpu_soft_limit_percent:.1f}%)."
            )
            time.sleep(self.limits.throttle_sleep_ms / 1000.0)
            throttled = True

        if warnings:
            self.warnings.extend(warnings)

        return {"throttled": throttled, "warnings": warnings}

    def profile(self) -> dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "tier": self.tier,
            "operations": self.operations,
            "peak_process_mem_mb": round(self.peak_process_mem_mb, 3),
            "last_cpu_percent": round(self.last_cpu_percent, 2),
            "limits": {
                "soft_process_mem_mb": self.limits.soft_process_mem_mb,
                "hard_process_mem_mb": self.limits.hard_process_mem_mb,
                "cpu_soft_limit_percent": self.limits.cpu_soft_limit_percent,
                "throttle_sleep_ms": self.limits.throttle_sleep_ms,
                "check_every_ops": self.limits.check_every_ops,
            },
            "warnings": list(self.warnings[-25:]),
        }

    def _default_process_probe(self) -> dict[str, float]:
        try:
            import psutil  # type: ignore
        except Exception:
            return {"mem_mb": 0.0, "cpu_percent": 0.0}

        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)
        cpu_percent = psutil.cpu_percent(interval=0.0)
        return {"mem_mb": mem_mb, "cpu_percent": cpu_percent}
