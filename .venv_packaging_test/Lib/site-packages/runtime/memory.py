from __future__ import annotations

import ctypes
import gc
import os
from typing import Any

MB = 1024 * 1024


class MemoryRuntimeError(Exception):
    pass


class MemoryManager:
    def __init__(
        self,
        preferred_mode: str | None = None,
        *,
        strict_checks: bool = True,
    ) -> None:
        self.strict_checks = strict_checks
        self.total_bytes = self.detect_total_memory_bytes()
        self.recommended_mode = self.recommend_mode(self.total_bytes)
        self.mode = self.recommended_mode
        self.allocations: dict[str, int] = {}
        self.last_gc_collected = 0
        self.peak_allocated_bytes = 0
        self.warning_messages: list[str] = []
        self.auto_gc_counter = 0
        if preferred_mode is not None:
            self.set_mode(preferred_mode)
        else:
            self.cap_bytes = self.mode_cap_bytes(self.mode)

    @staticmethod
    def detect_total_memory_bytes() -> int:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return max(int(stat.ullTotalPhys), 1)

        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(pages, int)
                and isinstance(page_size, int)
                and pages > 0
                and page_size > 0
            ):
                return pages * page_size

        return 8 * 1024 * 1024 * 1024

    @staticmethod
    def recommend_mode(total_bytes: int) -> str:
        total_gb = total_bytes / (1024**3)
        if total_gb <= 8:
            return "eco"
        if total_gb <= 16:
            return "balanced"
        return "turbo"

    def mode_cap_bytes(self, mode: str) -> int:
        if mode == "eco":
            return max(min(int(self.total_bytes * 0.18), 512 * MB), 64 * MB)
        if mode == "balanced":
            return max(min(int(self.total_bytes * 0.35), 2 * 1024 * MB), 128 * MB)
        if mode == "turbo":
            return max(min(int(self.total_bytes * 0.65), 8 * 1024 * MB), 256 * MB)
        raise MemoryRuntimeError("Unknown memory mode. Use one of: eco, balanced, turbo.")

    def set_mode(self, mode: str) -> dict[str, Any]:
        normalized = str(mode).strip().lower()
        self.cap_bytes = self.mode_cap_bytes(normalized)
        self.mode = normalized
        return self.profile()

    def auto_mode(self) -> dict[str, Any]:
        self.mode = self.recommended_mode
        self.cap_bytes = self.mode_cap_bytes(self.mode)
        return self.profile()

    def allocated_bytes(self) -> int:
        return sum(self.allocations.values())

    def alloc(self, name: Any, megabytes: Any) -> dict[str, Any]:
        block = str(name).strip()
        if not block:
            raise MemoryRuntimeError("Memory block name cannot be empty.")

        try:
            size_mb = float(megabytes)
        except Exception as exc:
            raise MemoryRuntimeError("memory.alloc(name, size) expects numeric size.") from exc
        if size_mb <= 0:
            raise MemoryRuntimeError("Allocated size must be greater than 0 MB.")

        size_bytes = int(size_mb * MB)
        if self.strict_checks:
            if block in self.allocations:
                raise MemoryRuntimeError(f"Memory block '{block}' already exists.")
            projected = self.allocated_bytes() + size_bytes
            if projected > self.cap_bytes:
                raise MemoryRuntimeError(
                    "Memory reservation exceeds current profile cap "
                    f"({self.cap_bytes / MB:.1f} MB)."
                )

        self.allocations[block] = size_bytes
        self.peak_allocated_bytes = max(self.peak_allocated_bytes, self.allocated_bytes())
        self._warn_if_near_cap()
        self._auto_gc_if_needed()
        return self.profile()

    def free(self, name: Any) -> float:
        block = str(name).strip()
        if block not in self.allocations:
            if self.strict_checks:
                raise MemoryRuntimeError(f"Memory block '{block}' does not exist.")
            return 0.0
        released = self.allocations.pop(block)
        self._auto_gc_if_needed(force=False)
        return round(released / MB, 3)

    def free_all(self) -> float:
        released = self.allocated_bytes()
        self.allocations.clear()
        self.gc_collect()
        return round(released / MB, 3)

    def gc_collect(self) -> int:
        self.last_gc_collected = gc.collect()
        return self.last_gc_collected

    def profile(self) -> dict[str, Any]:
        total_gb = self.total_bytes / (1024**3)
        return {
            "total_ram_gb": round(total_gb, 2),
            "mode": self.mode,
            "recommended_mode": self.recommended_mode,
            "cap_mb": round(self.cap_bytes / MB, 2),
            "allocated_mb": round(self.allocated_bytes() / MB, 3),
            "peak_allocated_mb": round(self.peak_allocated_bytes / MB, 3),
            "active_objects": len(self.allocations),
            "active_blocks": sorted(self.allocations.keys()),
            "last_gc_collected": self.last_gc_collected,
            "strict_checks": self.strict_checks,
            "warnings": list(self.warning_messages[-20:]),
            "auto_gc_counter": self.auto_gc_counter,
        }

    def _warn_if_near_cap(self) -> None:
        allocated = self.allocated_bytes()
        if self.cap_bytes <= 0:
            return
        usage_ratio = allocated / self.cap_bytes
        if usage_ratio >= 0.85:
            self.warning_messages.append(
                f"Memory nearing cap: {allocated / MB:.1f}MB / {self.cap_bytes / MB:.1f}MB."
            )

    def _auto_gc_if_needed(self, force: bool = False) -> None:
        allocated = self.allocated_bytes()
        if self.cap_bytes <= 0:
            return
        usage_ratio = allocated / self.cap_bytes
        if force or usage_ratio >= 0.90:
            self.gc_collect()
            self.auto_gc_counter += 1


class MemoryModule:
    def __init__(self, manager: MemoryManager, *, allow_mutation: bool = True) -> None:
        self._manager = manager
        self._allow_mutation = allow_mutation

    def _ensure_mutation_allowed(self) -> None:
        if not self._allow_mutation:
            raise MemoryRuntimeError(
                "Memory mutation is disabled in lightweight .k scripting mode."
            )

    def profile(self) -> dict[str, Any]:
        return self._manager.profile()

    def set_mode(self, mode: str) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        return self._manager.set_mode(mode)

    def auto(self) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        return self._manager.auto_mode()

    def alloc(self, name: str, megabytes: float) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        return self._manager.alloc(name, megabytes)

    def free(self, name: str) -> float:
        self._ensure_mutation_allowed()
        return self._manager.free(name)

    def free_all(self) -> float:
        self._ensure_mutation_allowed()
        return self._manager.free_all()

    def gc(self) -> int:
        self._ensure_mutation_allowed()
        return self._manager.gc_collect()

    def warnings(self) -> list[str]:
        return list(self._manager.warning_messages[-20:])

    def mode(self) -> str:
        return self._manager.mode
