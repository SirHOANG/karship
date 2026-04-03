from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ksharp.runtime import Interpreter
    from runtime.memory import MemoryManager


class AntiCheatRuntimeModule:
    def __init__(self, interpreter: "Interpreter", memory_manager: "MemoryManager") -> None:
        self._interpreter = interpreter
        self._memory_manager = memory_manager
        self._events: list[dict[str, Any]] = []
        self._hooks: dict[str, list[Any]] = {}

    def hook(self, event_name: str, handler: Any) -> int:
        name = str(event_name).strip()
        if not name:
            raise self._interpreter.runtime_error("anticheat.hook requires event name.")
        self._hooks.setdefault(name, []).append(handler)
        return len(self._hooks[name])

    def emit(self, event_name: str, payload: Any = None, severity: int = 1) -> dict[str, Any]:
        name = str(event_name).strip()
        sev = max(1, int(severity))
        entry = {
            "time": round(time.time(), 3),
            "event": name,
            "payload": payload,
            "severity": sev,
        }
        self._events.append(entry)
        for handler in self._hooks.get(name, []):
            self._invoke(handler, [entry])
        return entry

    def memory_scan(self, pattern: str | None = None) -> dict[str, Any]:
        allocs = self._memory_manager.allocations
        if pattern is None:
            matched = [{"name": k, "size_mb": round(v / (1024 * 1024), 3)} for k, v in allocs.items()]
        else:
            needle = str(pattern).lower()
            matched = [
                {"name": k, "size_mb": round(v / (1024 * 1024), 3)}
                for k, v in allocs.items()
                if needle in k.lower()
            ]
        suspicious = [item for item in matched if item["size_mb"] >= 128.0]
        return {
            "matched_blocks": matched,
            "suspicious_blocks": suspicious,
            "suspicious_count": len(suspicious),
        }

    def detect(self, threshold: int = 5) -> dict[str, Any]:
        total_score = sum(int(item.get("severity", 1)) for item in self._events)
        suspicious = total_score >= int(threshold)
        return {
            "total_events": len(self._events),
            "score": total_score,
            "threshold": int(threshold),
            "suspicious": suspicious,
        }

    def logs(self) -> list[dict[str, Any]]:
        return list(self._events)

    def _invoke(self, callee: Any, args: list[Any]) -> Any:
        if callable(callee):
            try:
                return callee(*args)
            except TypeError:
                return callee()
        return self._interpreter.call(callee, args)
