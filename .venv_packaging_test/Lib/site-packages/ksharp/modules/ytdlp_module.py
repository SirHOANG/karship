from __future__ import annotations

import shutil
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ksharp.runtime import Interpreter


class YTDLPRuntimeModule:
    def __init__(self, interpreter: "Interpreter") -> None:
        self._interpreter = interpreter
        self._cookie_file: str | None = None
        self._default_search_count = 1
        self._last_error: str | None = None

    def profile(self) -> dict[str, Any]:
        return {
            "has_yt_dlp": self._has_yt_dlp(),
            "cookie_file": self._cookie_file,
            "js_runtime": self._detect_js_runtime(),
            "default_search_count": self._default_search_count,
            "last_error": self._last_error,
        }

    def last_error(self) -> str | None:
        return self._last_error

    def set_cookie_file(self, path: str) -> str:
        candidate = str(path).strip()
        if not candidate:
            raise self._interpreter.runtime_error("ytdlp.set_cookie_file requires a file path.")
        self._cookie_file = candidate
        return candidate

    def clear_cookie_file(self) -> None:
        self._cookie_file = None

    def set_search_count(self, count: int) -> int:
        value = int(count)
        if value < 1:
            value = 1
        if value > 20:
            value = 20
        self._default_search_count = value
        return self._default_search_count

    def stream(self, query: str) -> dict[str, Any]:
        info = self._extract_info(str(query), search_count=self._default_search_count)
        entry = self._first_playable_entry(info)
        if entry is None:
            message = (
                "ytdlp.stream could not resolve a playable source. "
                "Try a direct video URL or a more specific search query."
            )
            self._last_error = message
            raise self._interpreter.runtime_error(message)
        stream_url = self._choose_best_audio_url(entry)
        if not stream_url:
            message = (
                "ytdlp.stream found no playable audio URL. "
                "The source may be unavailable/live-restricted right now."
            )
            self._last_error = message
            raise self._interpreter.runtime_error(message)

        payload = {
            "title": str(entry.get("title") or "Unknown title"),
            "source_url": str(entry.get("webpage_url") or query),
            "stream_url": str(stream_url),
            "duration": int(entry.get("duration") or 0),
            "thumbnail": entry.get("thumbnail"),
            "extractor": entry.get("extractor"),
        }
        self._last_error = None
        return payload

    def stream_url(self, query: str) -> str:
        return str(self.stream(query)["stream_url"])

    def tracks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        max_items = max(1, min(int(limit), 50))
        info = self._extract_info(str(query), search_count=max_items)
        entries = self._entries(info)[:max_items]
        items: list[dict[str, Any]] = []
        for entry in entries:
            audio_url = self._choose_best_audio_url(entry)
            if not audio_url:
                continue
            items.append(
                {
                    "title": str(entry.get("title") or "Unknown title"),
                    "source_url": str(entry.get("webpage_url") or query),
                    "stream_url": str(audio_url),
                    "duration": int(entry.get("duration") or 0),
                    "thumbnail": entry.get("thumbnail"),
                }
            )
        return items

    def _has_yt_dlp(self) -> bool:
        try:
            import yt_dlp  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def _extract_info(self, query: str, *, search_count: int) -> dict[str, Any]:
        if not self._has_yt_dlp():
            message = (
                "yt-dlp is not installed. Install with: kar install ytdlp.ksharp "
                "(or kar install yt-dlp --global)."
            )
            self._last_error = message
            raise self._interpreter.runtime_error(message)

        try:
            import yt_dlp  # type: ignore
        except Exception as exc:
            message = "Unable to import yt-dlp runtime."
            self._last_error = message
            raise self._interpreter.runtime_error(message) from exc

        target = query.strip()
        if not target:
            message = "ytdlp requires a non-empty URL or search query."
            self._last_error = message
            raise self._interpreter.runtime_error(message)

        attempts = self._build_extract_attempts(target, search_count=search_count)
        failures: list[str] = []
        for attempt in attempts:
            options = self._build_options()
            options.update(attempt["overrides"])
            try:
                info = self._extract_with_options(yt_dlp, attempt["target"], options)
            except Exception as exc:
                failures.append(f'{attempt["label"]}: {exc}')
                continue
            if not isinstance(info, dict):
                failures.append(f'{attempt["label"]}: unexpected metadata format')
                continue
            if not self._entries(info):
                failures.append(f'{attempt["label"]}: no entries returned')
                continue
            self._last_error = None
            return info

        message = self._format_extract_failure(failures)
        self._last_error = message
        raise self._interpreter.runtime_error(message)

    def _extract_with_options(
        self,
        yt_dlp_module: Any,
        target: str,
        options: dict[str, Any],
    ) -> Any:
        with yt_dlp_module.YoutubeDL(options) as engine:
            return engine.extract_info(target, download=False)

    def _build_extract_attempts(
        self,
        query: str,
        *,
        search_count: int,
    ) -> list[dict[str, Any]]:
        primary_target = self._normalize_target(query, search_count=search_count)
        attempts: list[dict[str, Any]] = [
            {
                "label": "primary",
                "target": primary_target,
                "overrides": {},
            },
            {
                "label": "network-retry",
                "target": primary_target,
                "overrides": {
                    "extractor_retries": 4,
                    "retries": 4,
                    "fragment_retries": 4,
                    "socket_timeout": 20,
                },
            },
        ]

        if "://" not in query:
            wider = max(3, min(10, search_count * 2))
            attempts.append(
                {
                    "label": "wider-search",
                    "target": f"ytsearch{wider}:{query}",
                    "overrides": {"default_search": "ytsearch"},
                }
            )
        else:
            attempts.append(
                {
                    "label": "single-video",
                    "target": query,
                    "overrides": {
                        "noplaylist": True,
                    },
                }
            )

        unique_attempts: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in attempts:
            key = (
                item["target"],
                str(sorted((str(k), str(v)) for k, v in item["overrides"].items())),
            )
            if key in seen:
                continue
            seen.add(key)
            unique_attempts.append(item)
        return unique_attempts

    @staticmethod
    def _normalize_target(query: str, *, search_count: int) -> str:
        trimmed = str(query).strip()
        if "://" in trimmed:
            return trimmed
        return f"ytsearch{max(1, search_count)}:{trimmed}"

    def _format_extract_failure(self, failures: list[str]) -> str:
        brief = "; ".join(failures[:3]) if failures else "unknown extraction error"
        return (
            "yt-dlp extraction failed after safe retries. "
            f"Details: {brief}. "
            "Tips: verify URL/search terms, update yt-dlp, and for restricted videos set "
            "a cookie file with ytdlp.set_cookie_file(...)."
        )

    def _build_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "format": "bestaudio/best",
            "noplaylist": False,
            "quiet": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "nocheckcertificate": True,
            "source_address": "0.0.0.0",
            "extractor_retries": 2,
            "retries": 2,
            "fragment_retries": 2,
            "socket_timeout": 15,
            "cachedir": False,
        }
        if self._cookie_file:
            options["cookiefile"] = self._cookie_file

        runtime = self._detect_js_runtime()
        if runtime:
            options["js_runtimes"] = {runtime: {"cmd": runtime}}
        return options

    def _detect_js_runtime(self) -> str | None:
        for runtime in ("deno", "node", "bun"):
            if shutil.which(runtime):
                return runtime
        return None

    @staticmethod
    def _entries(info: dict[str, Any]) -> list[dict[str, Any]]:
        if info.get("_type") == "playlist" and isinstance(info.get("entries"), list):
            return [item for item in info["entries"] if isinstance(item, dict)]
        if isinstance(info.get("entries"), list):
            return [item for item in info["entries"] if isinstance(item, dict)]
        return [info]

    @classmethod
    def _first_playable_entry(cls, info: dict[str, Any]) -> dict[str, Any] | None:
        for entry in cls._entries(info):
            if cls._choose_best_audio_url(entry):
                return entry
        return None

    @staticmethod
    def _choose_best_audio_url(info: dict[str, Any]) -> str | None:
        requested_formats = info.get("requested_formats")
        if isinstance(requested_formats, list):
            for requested in requested_formats:
                if not isinstance(requested, dict):
                    continue
                if requested.get("acodec") == "none":
                    continue
                if requested.get("url"):
                    return str(requested["url"])

        formats = info.get("formats")
        if isinstance(formats, list):
            best: dict[str, Any] | None = None
            for fmt in formats:
                if not isinstance(fmt, dict):
                    continue
                if fmt.get("acodec") == "none":
                    continue
                if best is None or (fmt.get("abr") or 0) > (best.get("abr") or 0):
                    best = fmt
            if best and best.get("url"):
                return str(best["url"])
        if info.get("url"):
            return str(info["url"])
        return None
