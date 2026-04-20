from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
import time
from typing import Any


class SecurityRuntimeModule:
    def __init__(self) -> None:
        self._logs: list[dict[str, Any]] = []

    def hash(self, text: Any) -> str:
        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    def safe_equal(self, left: Any, right: Any) -> bool:
        return hmac.compare_digest(str(left), str(right))

    def white_hat_only(self) -> str:
        return "Karship security mode is white-hat only."

    def log(self, event: str, payload: Any = None) -> dict[str, Any]:
        entry = {
            "time": round(time.time(), 3),
            "event": str(event),
            "payload": payload,
        }
        self._logs.append(entry)
        return entry

    def logs(self) -> list[dict[str, Any]]:
        return list(self._logs)

    def inspect_request(self, raw_request: str) -> dict[str, Any]:
        text = str(raw_request).replace("\r\n", "\n")
        lines = text.split("\n")
        request_line = lines[0] if lines else ""
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            headers[key.strip()] = value.strip()
        return {
            "request_line": request_line,
            "header_count": len(headers),
            "headers": headers,
        }

    def scan_host(
        self,
        host: str,
        ports: list[int] | None = None,
        timeout: float = 0.25,
        allow_external: bool = False,
    ) -> dict[str, Any]:
        target = str(host).strip()
        if not target:
            raise ValueError("scan_host requires a host.")
        if ports is None:
            ports = [21, 22, 25, 53, 80, 110, 143, 443, 3306, 5432, 6379, 8080]
        ports = [int(p) for p in ports][:64]

        resolved_ip = socket.gethostbyname(target)
        ip_obj = ipaddress.ip_address(resolved_ip)
        if not allow_external and not (ip_obj.is_private or ip_obj.is_loopback):
            raise ValueError(
                "External scanning is blocked by default. "
                "Use allow_external=true only with explicit authorization."
            )

        findings: list[dict[str, Any]] = []
        for port in ports:
            if port < 1 or port > 65535:
                continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(float(timeout))
            try:
                result = sock.connect_ex((resolved_ip, int(port)))
                findings.append({"port": int(port), "open": result == 0})
            finally:
                sock.close()

        open_ports = [item["port"] for item in findings if item["open"]]
        summary = {
            "target": target,
            "ip": resolved_ip,
            "ports_checked": len(findings),
            "open_ports": open_ports,
            "findings": findings,
            "ethics": "white-hat-only",
        }
        self.log("scan_host", {"target": target, "open_ports": open_ports})
        return summary
