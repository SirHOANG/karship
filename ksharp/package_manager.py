from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable

CONFIG_FILENAME = "karship.json"
LOCAL_RUNTIME_DIRNAME = ".karship"
LOCAL_SITE_PACKAGES_REL = Path(LOCAL_RUNTIME_DIRNAME) / "site-packages"
GLOBAL_PACKAGES_DIR_REL = Path("Karship") / "packages"
NATIVE_PACKAGE_VERSION = "native-0.1.0"
DISCORD_NATIVE_PACKAGE_ID = "discord-ksharp"
DISCORD_NATIVE_LIBRARY_NAME = "discord.ksharp"
YTDLP_NATIVE_PACKAGE_ID = "ytdlp-ksharp"
YTDLP_NATIVE_LIBRARY_NAME = "ytdlp.ksharp"
WEB_NATIVE_PACKAGE_ID = "web-ksharp"
WEB_NATIVE_LIBRARY_NAME = "web.ksharp"
DB_NATIVE_PACKAGE_ID = "db-ksharp"
DB_NATIVE_LIBRARY_NAME = "db.ksharp"
SECURITY_NATIVE_PACKAGE_ID = "security-ksharp"
SECURITY_NATIVE_LIBRARY_NAME = "security.ksharp"
GAME_NATIVE_PACKAGE_ID = "game-ksharp"
GAME_NATIVE_LIBRARY_NAME = "game.ksharp"
ANTICHEAT_NATIVE_PACKAGE_ID = "anticheat-ksharp"
ANTICHEAT_NATIVE_LIBRARY_NAME = "anticheat.ksharp"
SDK_NATIVE_PACKAGE_ID = "sdk-ksharp"
SDK_NATIVE_LIBRARY_NAME = "sdk.ksharp"
SYSTEM_NATIVE_PACKAGE_ID = "system-ksharp"
SYSTEM_NATIVE_LIBRARY_NAME = "system.ksharp"
MEMORY_NATIVE_PACKAGE_ID = "memory-ksharp"
MEMORY_NATIVE_LIBRARY_NAME = "memory.ksharp"
UTILS_NATIVE_PACKAGE_ID = "utils-ksharp"
UTILS_NATIVE_LIBRARY_NAME = "utils.ksharp"
COLLECTIONS_NATIVE_PACKAGE_ID = "collections-ksharp"
COLLECTIONS_NATIVE_LIBRARY_NAME = "collections.ksharp"
MATH_NATIVE_PACKAGE_ID = "math-ksharp"
MATH_NATIVE_LIBRARY_NAME = "math.ksharp"
DEVTOOLS_NATIVE_PACKAGE_ID = "devtools-ksharp"
DEVTOOLS_NATIVE_LIBRARY_NAME = "devtools.ksharp"
DISCORD_NATIVE_BRIDGE_DEPENDENCIES = ("discord.py", "PyNaCl", "yt-dlp>=2025.01.15")
YTDLP_NATIVE_BRIDGE_DEPENDENCIES = ("yt-dlp>=2025.01.15",)


class PackageManagerError(Exception):
    pass


@dataclass(slots=True, frozen=True)
class NativePackageSpec:
    package_id: str
    library_name: str
    description: str
    template_builder: Callable[[], str]
    python_bridge_dependencies: tuple[str, ...] = ()


def normalize_package_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", str(name).strip().lower())
    return normalized


@dataclass(slots=True)
class DependencyResolver:
    dependencies: dict[str, str]

    def validate(self) -> None:
        seen: set[str] = set()
        for raw_name, version in self.dependencies.items():
            name = normalize_package_name(raw_name)
            if not name or not re.fullmatch(r"[a-z0-9-]+", name):
                raise PackageManagerError(f"Invalid dependency name '{raw_name}'.")
            if name in seen:
                raise PackageManagerError(f"Duplicate dependency '{raw_name}'.")
            seen.add(name)
            if not isinstance(version, str) or not version.strip():
                raise PackageManagerError(
                    f"Dependency '{raw_name}' has an invalid version specifier."
                )


def default_project_config(project_name: str) -> dict[str, Any]:
    safe_name = project_name.strip() or "karship-app"
    return {
        "name": safe_name,
        "version": "0.1.0",
        "entry": "main.ksharp",
        "runtime": {
            "adaptive": True,
            "default_memory_mode": "auto",
        },
        "dependencies": {},
    }


def get_global_karship_packages_dir(*, create: bool = False) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home()
    package_dir = (base / GLOBAL_PACKAGES_DIR_REL).resolve()
    if create:
        package_dir.mkdir(parents=True, exist_ok=True)
    return package_dir


def find_project_root(start: str | Path | None = None) -> Path | None:
    base = Path(start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent
    for candidate in [base, *base.parents]:
        if (candidate / CONFIG_FILENAME).exists():
            return candidate
    return None


def load_project_config(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_path = root / CONFIG_FILENAME
    if not config_path.exists():
        raise PackageManagerError(f"Missing {CONFIG_FILENAME} at {root}.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackageManagerError(f"Invalid JSON in {CONFIG_FILENAME}.") from exc

    if not isinstance(config, dict):
        raise PackageManagerError(f"{CONFIG_FILENAME} root must be an object.")
    if "dependencies" not in config or not isinstance(config["dependencies"], dict):
        config["dependencies"] = {}

    dependencies = {
        normalize_package_name(str(key)): str(value)
        for key, value in config["dependencies"].items()
    }
    DependencyResolver(dependencies).validate()
    config["dependencies"] = dependencies
    return config


def save_project_config(project_root: str | Path, config: dict[str, Any]) -> Path:
    root = Path(project_root).resolve()
    config_path = root / CONFIG_FILENAME
    if "dependencies" not in config or not isinstance(config["dependencies"], dict):
        config["dependencies"] = {}
    DependencyResolver(
        {normalize_package_name(str(k)): str(v) for k, v in config["dependencies"].items()}
    ).validate()
    config["dependencies"] = {
        normalize_package_name(str(k)): str(v)
        for k, v in config["dependencies"].items()
    }
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return config_path


def ensure_local_site_packages(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    site_packages = root / LOCAL_SITE_PACKAGES_REL
    site_packages.mkdir(parents=True, exist_ok=True)
    return site_packages


def configure_python_path_for_project(project_root: str | Path | None) -> Path | None:
    if project_root is None:
        return None
    root = Path(project_root).resolve()
    site_packages = root / LOCAL_SITE_PACKAGES_REL
    if not site_packages.exists():
        return None
    site_as_str = str(site_packages)
    if site_as_str not in sys.path:
        sys.path.insert(0, site_as_str)
    return site_packages


def _normalize_native_package_id(package_name: str) -> str | None:
    normalized = normalize_package_name(package_name)
    if normalized in NATIVE_PACKAGE_SPECS:
        return normalized
    candidate = f"{normalized}-ksharp"
    if candidate in NATIVE_PACKAGE_SPECS:
        return candidate
    return None


def _discord_native_library_template() -> str:
    return dedent(
        """
        # discord.ksharp
        # Native Karship package for Discord bots.
        # Provides K# wrappers around runtime discord bridge, intents, scopes, and voice/music helpers.
        # For URL music playback, install ytdlp.ksharp and use discord_music_url.

        lock DISCORD_KSHARP_VERSION = "0.1.0"

        forge discord_package_info() {
            return "discord.ksharp " + DISCORD_KSHARP_VERSION
        }

        forge discord_create(prefix) {
            let bot = discord.create(prefix)
            bot.scope("bot")
            bot.scope("applications.commands")
            bot.intent("guilds", true)
            bot.intent("guild_messages", true)
            bot.intent("message_content", true)
            return bot
        }

        forge discord_on(bot, event_name, handler) {
            if event_name == "ready" {
                bot.on_ready(handler)
                return true
            }
            if event_name == "message" {
                bot.on_message(handler)
                return true
            }
            spark("discord_on unknown event:", event_name)
            return false
        }

        forge discord_command(bot, name, handler) {
            bot.command(name, handler)
            return true
        }

        forge discord_enable_voice(bot) {
            bot.intent("voice_states", true)
            bot.scope("voice")
            return true
        }

        forge discord_scope_all(bot) {
            bot.scope_all()
            return bot.scopes()
        }

        forge discord_intent_all(bot) {
            bot.intent_all()
            return bot.intents()
        }

        forge discord_portal_checklist(bot) {
            return bot.portal_checklist()
        }

        forge discord_music(bot, name, audio_path) {
            bot.music(name, audio_path)
            return true
        }

        forge discord_music_url(bot, name) {
            bot.music_url(name)
            return true
        }

        forge discord_music_url_default(bot, name, fallback_query) {
            bot.music_url(name, fallback_query)
            return true
        }

        forge discord_set_cookie_file(bot, cookie_file_path) {
            bot.set_cookie_file(cookie_file_path)
            return true
        }

        forge discord_ytdlp_resolve(bot, query) {
            return bot.ytdlp_resolve(query)
        }

        forge discord_invite(bot, client_id, permissions) {
            return bot.invite_url(client_id, permissions)
        }
        """
    ).strip() + "\n"


def _run_pip_command(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


def _base_requirement_name(requirement: str) -> str:
    text = str(requirement).strip()
    if not text:
        return ""
    base = re.split(r"[<>=!~;\s]", text, maxsplit=1)[0]
    return normalize_package_name(base)


def _ytdlp_native_library_template() -> str:
    return dedent(
        """
        # ytdlp.ksharp
        # Native Karship package for extracting playable audio streams with yt-dlp.
        # This package is for legitimate playback workflows and follows platform/usage rules.

        lock YTDLP_KSHARP_VERSION = "0.1.0"

        forge ytdlp_info() {
            return "ytdlp.ksharp " + YTDLP_KSHARP_VERSION
        }

        forge ytdlp_profile() {
            return ytdlp.profile()
        }

        forge ytdlp_last_error() {
            return ytdlp.last_error()
        }

        forge ytdlp_set_cookie_file(path) {
            return ytdlp.set_cookie_file(path)
        }

        forge ytdlp_clear_cookie_file() {
            ytdlp.clear_cookie_file()
            return true
        }

        forge ytdlp_search_count(count) {
            return ytdlp.set_search_count(count)
        }

        forge ytdlp_stream(query) {
            return ytdlp.stream(query)
        }

        forge ytdlp_stream_url(query) {
            return ytdlp.stream_url(query)
        }

        forge ytdlp_tracks(query, limit) {
            return ytdlp.tracks(query, limit)
        }
        """
    ).strip() + "\n"


def _web_native_library_template() -> str:
    return dedent(
        """
        # web.ksharp
        # Native Karship web helper package.

        lock WEB_KSHARP_VERSION = "0.1.0"

        forge web_info() {
            return "web.ksharp " + WEB_KSHARP_VERSION
        }

        forge web_create(host, port) {
            return web.create_server(host, port)
        }

        forge web_route(server, path, handler) {
            server.route(path, handler)
            return true
        }

        forge web_routes(server) {
            return server.routes()
        }

        forge web_run(server) {
            return server.run()
        }

        forge web_stop(server) {
            return server.stop()
        }

        forge web_page(title, body_html) {
            return web.page(title, body_html)
        }

        forge web_json(value) {
            return web.json(value)
        }
        """
    ).strip() + "\n"


def _db_native_library_template() -> str:
    return dedent(
        """
        # db.ksharp
        # Native Karship sqlite helper package.

        lock DB_KSHARP_VERSION = "0.1.0"

        forge db_info() {
            return "db.ksharp " + DB_KSHARP_VERSION
        }

        forge db_connect(path) {
            return db.open(path)
        }

        forge db_exec(conn, sql) {
            return conn.exec(sql)
        }

        forge db_exec_params(conn, sql, params) {
            return conn.exec(sql, params)
        }

        forge db_query(conn, sql) {
            return conn.query(sql)
        }

        forge db_query_params(conn, sql, params) {
            return conn.query(sql, params)
        }

        forge db_one(conn, sql) {
            let rows = conn.query(sql)
            if len(rows) == 0 {
                return nil
            }
            return rows[0]
        }

        forge db_one_params(conn, sql, params) {
            let rows = conn.query(sql, params)
            if len(rows) == 0 {
                return nil
            }
            return rows[0]
        }

        forge db_close(conn) {
            conn.close()
            return true
        }
        """
    ).strip() + "\n"


def _security_native_library_template() -> str:
    return dedent(
        """
        # security.ksharp
        # White-hat security helper package.

        lock SECURITY_KSHARP_VERSION = "0.1.0"

        forge security_info() {
            return "security.ksharp " + SECURITY_KSHARP_VERSION
        }

        forge sec_policy() {
            return security.white_hat_only()
        }

        forge sec_hash(text) {
            return security.hash(text)
        }

        forge sec_safe_equal(left, right) {
            return security.safe_equal(left, right)
        }

        forge sec_log(event_name, payload) {
            return security.log(event_name, payload)
        }

        forge sec_logs() {
            return security.logs()
        }

        forge sec_inspect_request(raw_request) {
            return security.inspect_request(raw_request)
        }

        forge sec_scan_local(host, ports) {
            return security.scan_host(host, ports, 0.25, false)
        }

        forge sec_scan_authorized(host, ports, timeout) {
            return security.scan_host(host, ports, timeout, true)
        }
        """
    ).strip() + "\n"


def _game_native_library_template() -> str:
    return dedent(
        """
        # game.ksharp
        # Game loop and input helper package.

        lock GAME_KSHARP_VERSION = "0.1.0"

        forge game_info() {
            return "game.ksharp " + GAME_KSHARP_VERSION
        }

        forge game_loop(fps) {
            return game.create_loop(fps)
        }

        forge game_on_update(loop, handler) {
            loop.on_update(handler)
            return true
        }

        forge game_on_render(loop, handler) {
            loop.on_render(handler)
            return true
        }

        forge game_run(loop, seconds, max_frames) {
            return loop.run(seconds, max_frames)
        }

        forge game_stop(loop) {
            loop.stop()
            return true
        }

        forge game_stats(loop) {
            return loop.stats()
        }

        forge game_key_down(key) {
            game.key_down(key)
            return true
        }

        forge game_key_up(key) {
            game.key_up(key)
            return true
        }

        forge game_is_pressed(key) {
            return game.is_pressed(key)
        }
        """
    ).strip() + "\n"


def _anticheat_native_library_template() -> str:
    return dedent(
        """
        # anticheat.ksharp
        # Anti-cheat and behavior monitoring helper package.

        lock ANTICHEAT_KSHARP_VERSION = "0.1.0"

        forge anticheat_info() {
            return "anticheat.ksharp " + ANTICHEAT_KSHARP_VERSION
        }

        forge anticheat_hook(event_name, handler) {
            return anticheat.hook(event_name, handler)
        }

        forge anticheat_emit(event_name, payload, severity) {
            return anticheat.emit(event_name, payload, severity)
        }

        forge anticheat_scan(pattern) {
            return anticheat.memory_scan(pattern)
        }

        forge anticheat_detect(threshold) {
            return anticheat.detect(threshold)
        }

        forge anticheat_logs() {
            return anticheat.logs()
        }
        """
    ).strip() + "\n"


def _sdk_native_library_template() -> str:
    return dedent(
        """
        # sdk.ksharp
        # JSON/serialization helpers.

        lock SDK_KSHARP_VERSION = "0.1.0"

        forge sdk_info() {
            return "sdk.ksharp " + SDK_KSHARP_VERSION
        }

        forge sdk_json_encode(value) {
            return sdk.to_json(value)
        }

        forge sdk_json_decode(text) {
            return sdk.from_json(text)
        }
        """
    ).strip() + "\n"


def _system_native_library_template() -> str:
    return dedent(
        """
        # system.ksharp
        # Adaptive hardware/runtime insight helpers.

        lock SYSTEM_KSHARP_VERSION = "0.1.0"

        forge system_info() {
            return "system.ksharp " + SYSTEM_KSHARP_VERSION
        }

        forge system_profile() {
            return system.profile()
        }

        forge system_refresh() {
            return system.refresh()
        }

        forge system_tier() {
            return system.tier()
        }

        forge system_recommended_mode() {
            return system.recommended_mode()
        }

        forge system_recommended_concurrency() {
            return system.recommended_concurrency()
        }

        forge system_monitor() {
            return system.monitor()
        }

        forge system_memory() {
            return system.memory()
        }

        forge system_warnings() {
            return system.warnings()
        }

        forge system_doctor() {
            return system.doctor()
        }
        """
    ).strip() + "\n"


def _memory_native_library_template() -> str:
    return dedent(
        """
        # memory.ksharp
        # Memory profile and allocation helpers.

        lock MEMORY_KSHARP_VERSION = "0.1.0"

        forge memory_info() {
            return "memory.ksharp " + MEMORY_KSHARP_VERSION
        }

        forge mem_profile() {
            return memory.profile()
        }

        forge mem_mode(mode) {
            return memory.set_mode(mode)
        }

        forge mem_auto() {
            return memory.auto()
        }

        forge mem_alloc(name, size_mb) {
            return memory.alloc(name, size_mb)
        }

        forge mem_free(name) {
            return memory.free(name)
        }

        forge mem_free_all() {
            return memory.free_all()
        }

        forge mem_gc() {
            return memory.gc()
        }

        forge mem_warnings() {
            return memory.warnings()
        }
        """
    ).strip() + "\n"


def _utils_native_library_template() -> str:
    return dedent(
        """
        # utils.ksharp
        # General utility helpers for everyday coding.

        lock UTILS_KSHARP_VERSION = "0.1.0"

        forge utils_info() {
            return "utils.ksharp " + UTILS_KSHARP_VERSION
        }

        forge now_epoch() {
            return clock()
        }

        forge clamp(value, min_value, max_value) {
            if value < min_value {
                return min_value
            }
            if value > max_value {
                return max_value
            }
            return value
        }

        forge between(value, min_value, max_value) {
            return value >= min_value and value <= max_value
        }

        forge coalesce(value, fallback) {
            if value == nil {
                return fallback
            }
            return value
        }

        forge repeat_text(text, count) {
            return to_str(text) * to_int(count)
        }

        forge join_lines(lines) {
            let out = ""
            each line in lines {
                if out == "" {
                    out = to_str(line)
                } else {
                    out = out + "\\n" + to_str(line)
                }
            }
            return out
        }
        """
    ).strip() + "\n"


def _collections_native_library_template() -> str:
    return dedent(
        """
        # collections.ksharp
        # List-centric helpers inspired by common Python/Lua workflows.

        lock COLLECTIONS_KSHARP_VERSION = "0.1.0"

        forge collections_info() {
            return "collections.ksharp " + COLLECTIONS_KSHARP_VERSION
        }

        forge list_size(items) {
            return len(items)
        }

        forge list_push(items, value) {
            items.append(value)
            return len(items)
        }

        forge list_pop(items) {
            return items.pop()
        }

        forge list_copy(items) {
            let out = []
            each item in items {
                out.append(item)
            }
            return out
        }

        forge list_find(items, needle) {
            let index = 0
            each item in items {
                if item == needle {
                    return index
                }
                index = index + 1
            }
            return -1
        }
        """
    ).strip() + "\n"


def _math_native_library_template() -> str:
    return dedent(
        """
        # math.ksharp
        # Lightweight math helpers.

        lock MATH_KSHARP_VERSION = "0.1.0"

        forge math_info() {
            return "math.ksharp " + MATH_KSHARP_VERSION
        }

        forge abs_value(value) {
            if value < 0 {
                return 0 - value
            }
            return value
        }

        forge min_value(a, b) {
            if a < b {
                return a
            }
            return b
        }

        forge max_value(a, b) {
            if a > b {
                return a
            }
            return b
        }

        forge power_int(base, exp) {
            let result = 1
            let i = 0
            while i < exp {
                result = result * base
                i = i + 1
            }
            return result
        }

        forge sqrt_newton(value, steps) {
            if value <= 0 {
                return 0
            }
            let guess = value
            let i = 0
            while i < steps {
                guess = 0.5 * (guess + (value / guess))
                i = i + 1
            }
            return guess
        }
        """
    ).strip() + "\n"


def _devtools_native_library_template() -> str:
    return dedent(
        """
        # devtools.ksharp
        # Debug and profiling helpers.

        lock DEVTOOLS_KSHARP_VERSION = "0.1.0"

        forge devtools_info() {
            return "devtools.ksharp " + DEVTOOLS_KSHARP_VERSION
        }

        forge dev_log(label, value) {
            spark("[dev]", label, "=>", value)
            return value
        }

        forge dev_timer_start() {
            return clock()
        }

        forge dev_timer_end(start_time, label) {
            let elapsed = clock() - start_time
            spark("[timer]", label, "elapsed:", elapsed)
            return elapsed
        }

        forge dev_assert(condition, message) {
            if condition {
                return true
            }
            spark("[assert-failed]", message)
            return false
        }

        forge dev_snapshot() {
            spark("[system]", system.profile())
            spark("[memory]", memory.profile())
            return true
        }
        """
    ).strip() + "\n"


NATIVE_PACKAGE_SPECS: dict[str, NativePackageSpec] = {
    DISCORD_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=DISCORD_NATIVE_PACKAGE_ID,
        library_name=DISCORD_NATIVE_LIBRARY_NAME,
        description="Discord bot helpers with intents, commands, and voice bridge support.",
        template_builder=_discord_native_library_template,
        python_bridge_dependencies=DISCORD_NATIVE_BRIDGE_DEPENDENCIES,
    ),
    YTDLP_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=YTDLP_NATIVE_PACKAGE_ID,
        library_name=YTDLP_NATIVE_LIBRARY_NAME,
        description="Safe yt-dlp stream metadata helpers for music and audio bots.",
        template_builder=_ytdlp_native_library_template,
        python_bridge_dependencies=YTDLP_NATIVE_BRIDGE_DEPENDENCIES,
    ),
    WEB_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=WEB_NATIVE_PACKAGE_ID,
        library_name=WEB_NATIVE_LIBRARY_NAME,
        description="HTTP server, routing, HTML/JSON response helpers.",
        template_builder=_web_native_library_template,
    ),
    DB_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=DB_NATIVE_PACKAGE_ID,
        library_name=DB_NATIVE_LIBRARY_NAME,
        description="SQLite query helpers with simple one-row shortcuts.",
        template_builder=_db_native_library_template,
    ),
    SECURITY_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=SECURITY_NATIVE_PACKAGE_ID,
        library_name=SECURITY_NATIVE_LIBRARY_NAME,
        description="White-hat logging, hashing, request inspection, and safe scanning tools.",
        template_builder=_security_native_library_template,
    ),
    GAME_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=GAME_NATIVE_PACKAGE_ID,
        library_name=GAME_NATIVE_LIBRARY_NAME,
        description="Game-loop and input helpers for prototypes.",
        template_builder=_game_native_library_template,
    ),
    ANTICHEAT_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=ANTICHEAT_NATIVE_PACKAGE_ID,
        library_name=ANTICHEAT_NATIVE_LIBRARY_NAME,
        description="Event hooks and memory-scan simulation for anti-cheat workflows.",
        template_builder=_anticheat_native_library_template,
    ),
    SDK_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=SDK_NATIVE_PACKAGE_ID,
        library_name=SDK_NATIVE_LIBRARY_NAME,
        description="JSON encode/decode helpers for APIs and SDK integration.",
        template_builder=_sdk_native_library_template,
    ),
    SYSTEM_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=SYSTEM_NATIVE_PACKAGE_ID,
        library_name=SYSTEM_NATIVE_LIBRARY_NAME,
        description="Hardware/runtime profile helpers for adaptive behavior.",
        template_builder=_system_native_library_template,
    ),
    MEMORY_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=MEMORY_NATIVE_PACKAGE_ID,
        library_name=MEMORY_NATIVE_LIBRARY_NAME,
        description="Memory profile and allocation lifecycle wrappers.",
        template_builder=_memory_native_library_template,
    ),
    UTILS_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=UTILS_NATIVE_PACKAGE_ID,
        library_name=UTILS_NATIVE_LIBRARY_NAME,
        description="General-purpose utility helpers for day-to-day coding.",
        template_builder=_utils_native_library_template,
    ),
    COLLECTIONS_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=COLLECTIONS_NATIVE_PACKAGE_ID,
        library_name=COLLECTIONS_NATIVE_LIBRARY_NAME,
        description="List operations similar to common Python/Lua workflows.",
        template_builder=_collections_native_library_template,
    ),
    MATH_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=MATH_NATIVE_PACKAGE_ID,
        library_name=MATH_NATIVE_LIBRARY_NAME,
        description="Core math utilities (abs/min/max/power/sqrt approximation).",
        template_builder=_math_native_library_template,
    ),
    DEVTOOLS_NATIVE_PACKAGE_ID: NativePackageSpec(
        package_id=DEVTOOLS_NATIVE_PACKAGE_ID,
        library_name=DEVTOOLS_NATIVE_LIBRARY_NAME,
        description="Debug logs, assertions, timers, and quick runtime snapshots.",
        template_builder=_devtools_native_library_template,
    ),
}


def native_package_ids() -> list[str]:
    return sorted(NATIVE_PACKAGE_SPECS.keys())


def native_package_summaries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package_id in native_package_ids():
        spec = NATIVE_PACKAGE_SPECS[package_id]
        rows.append(
            {
                "package": spec.package_id,
                "library": spec.library_name,
                "description": spec.description,
                "python_bridge_dependencies": list(spec.python_bridge_dependencies),
            }
        )
    return rows


def is_native_package_name(package_name: str) -> bool:
    return _normalize_native_package_id(package_name) is not None


def _install_native_ytdlp_package(
    *,
    project_root: str | Path | None,
    global_install: bool,
    python_executable: str | None,
    install_python_bridge: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    bridge_result: dict[str, Any] | None = None

    if global_install:
        install_scope = "global"
        package_dir = get_global_karship_packages_dir(create=True)
        library_path = package_dir / YTDLP_NATIVE_LIBRARY_NAME
        site_packages_path: Path | None = None
        root: Path | None = None
    else:
        if project_root is None:
            raise PackageManagerError(
                f"Local install requires a Karship project root with {CONFIG_FILENAME}."
            )
        install_scope = "local"
        root = Path(project_root).resolve()
        libs_dir = root / "libs"
        libs_dir.mkdir(parents=True, exist_ok=True)
        library_path = libs_dir / YTDLP_NATIVE_LIBRARY_NAME
        site_packages_path = ensure_local_site_packages(root)

    library_path.write_text(_ytdlp_native_library_template(), encoding="utf-8")

    if not global_install and root is not None:
        config = load_project_config(root)
        deps = config.setdefault("dependencies", {})
        deps[YTDLP_NATIVE_PACKAGE_ID] = NATIVE_PACKAGE_VERSION
        save_project_config(root, config)

    if install_python_bridge:
        python_cmd = python_executable or sys.executable
        command = [python_cmd, "-m", "pip", "install", *YTDLP_NATIVE_BRIDGE_DEPENDENCIES]
        if not global_install and site_packages_path is not None:
            command.extend(["--target", str(site_packages_path)])
        bridge_result = _run_pip_command(command)
        if not bridge_result["ok"]:
            warnings.append(
                "yt-dlp install failed. Install manually when internet is available: "
                "kar install yt-dlp --global"
            )

    return {
        "package": YTDLP_NATIVE_PACKAGE_ID,
        "scope": install_scope,
        "version": NATIVE_PACKAGE_VERSION,
        "native": True,
        "library_path": str(library_path),
        "python_bridge_dependencies": list(YTDLP_NATIVE_BRIDGE_DEPENDENCIES),
        "python_bridge": bridge_result,
        "warnings": warnings,
    }


def _install_native_discord_package(
    *,
    project_root: str | Path | None,
    global_install: bool,
    python_executable: str | None,
    install_python_bridge: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    bridge_result: dict[str, Any] | None = None

    if global_install:
        install_scope = "global"
        package_dir = get_global_karship_packages_dir(create=True)
        library_path = package_dir / DISCORD_NATIVE_LIBRARY_NAME
        site_packages_path: Path | None = None
        root: Path | None = None
    else:
        if project_root is None:
            raise PackageManagerError(
                f"Local install requires a Karship project root with {CONFIG_FILENAME}."
            )
        install_scope = "local"
        root = Path(project_root).resolve()
        libs_dir = root / "libs"
        libs_dir.mkdir(parents=True, exist_ok=True)
        library_path = libs_dir / DISCORD_NATIVE_LIBRARY_NAME
        site_packages_path = ensure_local_site_packages(root)

    library_path.write_text(_discord_native_library_template(), encoding="utf-8")

    if not global_install and root is not None:
        config = load_project_config(root)
        deps = config.setdefault("dependencies", {})
        deps[DISCORD_NATIVE_PACKAGE_ID] = NATIVE_PACKAGE_VERSION
        save_project_config(root, config)

    if install_python_bridge:
        python_cmd = python_executable or sys.executable
        command = [python_cmd, "-m", "pip", "install", *DISCORD_NATIVE_BRIDGE_DEPENDENCIES]
        if not global_install and site_packages_path is not None:
            command.extend(["--target", str(site_packages_path)])
        bridge_result = _run_pip_command(command)
        if not bridge_result["ok"]:
            warnings.append(
                "Python bridge dependency install failed. "
                "Run manually when internet is available: "
                "kar install discord.py --global"
            )

    return {
        "package": DISCORD_NATIVE_PACKAGE_ID,
        "scope": install_scope,
        "version": NATIVE_PACKAGE_VERSION,
        "native": True,
        "library_path": str(library_path),
        "python_bridge_dependencies": list(DISCORD_NATIVE_BRIDGE_DEPENDENCIES),
        "python_bridge": bridge_result,
        "warnings": warnings,
    }


def _install_native_package(
    native_package_id: str,
    *,
    project_root: str | Path | None,
    global_install: bool,
    python_executable: str | None,
    install_python_bridge: bool,
) -> dict[str, Any]:
    spec = NATIVE_PACKAGE_SPECS[native_package_id]
    warnings: list[str] = []
    bridge_result: dict[str, Any] | None = None

    if global_install:
        install_scope = "global"
        package_dir = get_global_karship_packages_dir(create=True)
        library_path = package_dir / spec.library_name
        site_packages_path: Path | None = None
        root: Path | None = None
    else:
        if project_root is None:
            raise PackageManagerError(
                f"Local install requires a Karship project root with {CONFIG_FILENAME}."
            )
        install_scope = "local"
        root = Path(project_root).resolve()
        libs_dir = root / "libs"
        libs_dir.mkdir(parents=True, exist_ok=True)
        library_path = libs_dir / spec.library_name
        site_packages_path = ensure_local_site_packages(root)

    library_path.write_text(spec.template_builder(), encoding="utf-8")

    if not global_install and root is not None:
        config = load_project_config(root)
        deps = config.setdefault("dependencies", {})
        deps[spec.package_id] = NATIVE_PACKAGE_VERSION
        save_project_config(root, config)

    if install_python_bridge and spec.python_bridge_dependencies:
        python_cmd = python_executable or sys.executable
        command = [python_cmd, "-m", "pip", "install", *spec.python_bridge_dependencies]
        if not global_install and site_packages_path is not None:
            command.extend(["--target", str(site_packages_path)])
        bridge_result = _run_pip_command(command)
        if not bridge_result["ok"]:
            warnings.append(
                f"Python bridge dependency install failed for {spec.package_id}. "
                f"Install manually when internet is available: kar install {' '.join(spec.python_bridge_dependencies)} --global"
            )

    return {
        "package": spec.package_id,
        "scope": install_scope,
        "version": NATIVE_PACKAGE_VERSION,
        "native": True,
        "library_path": str(library_path),
        "description": spec.description,
        "python_bridge_dependencies": list(spec.python_bridge_dependencies),
        "python_bridge": bridge_result,
        "warnings": warnings,
    }


def _remove_native_package(
    native_package_id: str,
    *,
    project_root: str | Path | None,
    global_install: bool,
    python_executable: str | None,
    remove_python_bridge: bool,
) -> dict[str, Any]:
    spec = NATIVE_PACKAGE_SPECS[native_package_id]
    warnings: list[str] = []
    removed_count = 0

    if global_install:
        library_path = get_global_karship_packages_dir(create=False) / spec.library_name
        if library_path.exists():
            library_path.unlink(missing_ok=True)
            removed_count += 1

        if remove_python_bridge and spec.python_bridge_dependencies:
            python_cmd = python_executable or sys.executable
            command = [python_cmd, "-m", "pip", "uninstall", "-y", *spec.python_bridge_dependencies]
            bridge = _run_pip_command(command)
            if not bridge["ok"]:
                warnings.append(
                    f"Could not fully uninstall Python bridge dependencies for {spec.package_id}."
                )

        return {
            "package": spec.package_id,
            "scope": "global",
            "removed_count": removed_count,
            "warnings": warnings,
        }

    if project_root is None:
        raise PackageManagerError("Local remove requires a Karship project root.")
    root = Path(project_root).resolve()
    library_path = root / "libs" / spec.library_name
    if library_path.exists():
        library_path.unlink(missing_ok=True)
        removed_count += 1

    if remove_python_bridge and spec.python_bridge_dependencies:
        site_packages = root / LOCAL_SITE_PACKAGES_REL
        for requirement in spec.python_bridge_dependencies:
            base_name = _base_requirement_name(requirement)
            if not base_name:
                continue
            removed_count += len(_remove_local_package_files(site_packages, base_name))

    config = load_project_config(root)
    dependencies = config.setdefault("dependencies", {})
    dependencies.pop(spec.package_id, None)
    save_project_config(root, config)

    return {
        "package": spec.package_id,
        "scope": "local",
        "removed_count": removed_count,
        "target": str(root / "libs"),
        "warnings": warnings,
    }


def init_project(project_root: str | Path, name: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_FILENAME
    if config_path.exists():
        raise PackageManagerError(f"{CONFIG_FILENAME} already exists at {root}.")

    project_name = name or root.name
    config = default_project_config(project_name)
    save_project_config(root, config)
    ensure_local_site_packages(root)
    (root / "libs").mkdir(parents=True, exist_ok=True)

    main_path = root / "main.ksharp"
    if not main_path.exists():
        main_path.write_text(
            'spark("Karship K# project ready")\n',
            encoding="utf-8",
        )

    return {
        "project_root": str(root),
        "config_path": str(config_path),
        "entry": str(main_path),
    }


def list_local_packages(project_root: str | Path) -> dict[str, str]:
    site_packages = Path(project_root).resolve() / LOCAL_SITE_PACKAGES_REL
    if not site_packages.exists():
        return {}
    results: dict[str, str] = {}
    for dist in importlib.metadata.distributions(path=[str(site_packages)]):
        name = normalize_package_name(str(dist.metadata.get("Name", "")))
        if not name:
            continue
        results[name] = str(dist.version)
    return dict(sorted(results.items()))


def _resolve_installed_version(package_name: str, search_paths: list[Path] | None = None) -> str | None:
    normalized = normalize_package_name(package_name)
    if not normalized:
        return None
    try:
        if search_paths:
            for dist in importlib.metadata.distributions(path=[str(path) for path in search_paths]):
                name = normalize_package_name(str(dist.metadata.get("Name", "")))
                if name == normalized:
                    return str(dist.version)
            return None
        return importlib.metadata.version(normalized)
    except Exception:
        return None


def install_package(
    package: str,
    *,
    project_root: str | Path | None = None,
    global_install: bool = False,
    python_executable: str | None = None,
    install_python_bridge: bool = True,
) -> dict[str, Any]:
    package_name = str(package).strip()
    if not package_name:
        raise PackageManagerError("Package name cannot be empty.")
    native_package = _normalize_native_package_id(package_name)
    if native_package is not None:
        return _install_native_package(
            native_package,
            project_root=project_root,
            global_install=global_install,
            python_executable=python_executable,
            install_python_bridge=install_python_bridge,
        )

    python_cmd = python_executable or sys.executable
    command = [python_cmd, "-m", "pip", "install", package_name]
    install_scope = "global"
    site_packages_path: Path | None = None

    if not global_install:
        if project_root is None:
            raise PackageManagerError(
                "Local install requires a Karship project root with karship.json."
            )
        site_packages_path = ensure_local_site_packages(project_root)
        command.extend(["--target", str(site_packages_path)])
        install_scope = "local"

    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "pip install failed."
        raise PackageManagerError(message)

    version = _resolve_installed_version(
        package_name,
        [site_packages_path] if site_packages_path is not None else None,
    ) or "latest"

    if not global_install and project_root is not None:
        root = Path(project_root).resolve()
        config = load_project_config(root)
        deps = config.setdefault("dependencies", {})
        deps[normalize_package_name(package_name)] = version
        save_project_config(root, config)

    return {
        "package": normalize_package_name(package_name),
        "scope": install_scope,
        "version": version,
        "target": str(site_packages_path) if site_packages_path is not None else "python-env",
        "output": proc.stdout.strip(),
    }


def _remove_local_package_files(site_packages: Path, package_name: str) -> list[Path]:
    removed: list[Path] = []
    if not site_packages.exists():
        return removed

    normalized = normalize_package_name(package_name)
    candidate_prefixes = {normalized, normalized.replace("-", "_")}

    for child in list(site_packages.iterdir()):
        child_name = normalize_package_name(child.stem if child.suffix else child.name)
        if (
            child_name in candidate_prefixes
            or any(child_name.startswith(f"{prefix}-") for prefix in candidate_prefixes)
        ):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=False)
            else:
                child.unlink(missing_ok=True)
            removed.append(child)
    return removed


def remove_package(
    package: str,
    *,
    project_root: str | Path | None = None,
    global_install: bool = False,
    python_executable: str | None = None,
    remove_python_bridge: bool = True,
) -> dict[str, Any]:
    package_name = str(package).strip()
    if not package_name:
        raise PackageManagerError("Package name cannot be empty.")

    native_package = _normalize_native_package_id(package_name)
    if native_package is not None:
        return _remove_native_package(
            native_package,
            project_root=project_root,
            global_install=global_install,
            python_executable=python_executable,
            remove_python_bridge=remove_python_bridge,
        )

    normalized = normalize_package_name(package_name)

    if global_install:
        python_cmd = python_executable or sys.executable
        command = [python_cmd, "-m", "pip", "uninstall", "-y", package_name]
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "pip uninstall failed."
            raise PackageManagerError(message)
        return {
            "package": normalized,
            "scope": "global",
            "removed_count": 1,
            "output": proc.stdout.strip(),
        }

    if project_root is None:
        raise PackageManagerError("Local remove requires a Karship project root.")
    root = Path(project_root).resolve()
    site_packages = root / LOCAL_SITE_PACKAGES_REL
    removed = _remove_local_package_files(site_packages, normalized)

    config = load_project_config(root)
    dependencies = config.setdefault("dependencies", {})
    dependencies.pop(normalized, None)
    save_project_config(root, config)

    return {
        "package": normalized,
        "scope": "local",
        "removed_count": len(removed),
        "target": str(site_packages),
    }
