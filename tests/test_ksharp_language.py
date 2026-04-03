import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
import sys
import types

from ksharp.kar_cli import main as kar_main
from ksharp.ksharp_interpreter import KSharpError, run_file, run_source
from ksharp.modules.discord_module import DiscordBotBridge
from ksharp.modules.ytdlp_module import YTDLPRuntimeModule
from ksharp.package_manager import (
    LOCAL_SITE_PACKAGES_REL,
    init_project,
    install_package,
    load_project_config,
    native_package_ids,
    remove_package,
)
from ksharp.runtime import Interpreter


class KSharpLanguageTests(unittest.TestCase):
    def test_spark_and_function(self) -> None:
        source = """
let greeting = "Karship"
spark("Hello", greeting)

forge add(a, b) {
    return a + b
}
spark(add(2, 3))
"""
        result = run_source(source, filename="<test>", emit_stdout=False)
        self.assertEqual(result.output[0], "Hello Karship")
        self.assertEqual(result.output[1], "5")

    def test_each_loop_and_range(self) -> None:
        source = """
let total = 0
each n in range(1, 5) {
    total = total + n
}
spark(total)
"""
        result = run_source(source, filename="<test>", emit_stdout=False)
        self.assertEqual(result.output, ["10"])

    def test_lock_prevents_reassignment(self) -> None:
        source = """
lock token = "abc"
token = "xyz"
"""
        with self.assertRaises(KSharpError):
            run_source(source, filename="<test>", emit_stdout=False)

    def test_db_module_query(self) -> None:
        source = """
let conn = db.open(":memory:")
conn.exec("create table users(name text)")
conn.exec("insert into users(name) values(?)", ["Alice"])
let rows = conn.query("select name from users")
spark(rows[0]["name"])
conn.close()
"""
        result = run_source(source, filename="<test>", emit_stdout=False)
        self.assertEqual(result.output, ["Alice"])

    def test_use_library_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "hello.ksharp").write_text(
                'forge hello(name) { return "Hello " + name }',
                encoding="utf-8",
            )
            (temp_path / "app.ksharp").write_text(
                'use "hello.ksharp"\nspark(hello("Karship"))',
                encoding="utf-8",
            )

            result = run_file(temp_path / "app.ksharp", emit_stdout=False)
            self.assertEqual(result.output, ["Hello Karship"])

    def test_memory_profiles_and_manual_alloc(self) -> None:
        source = """
memory.set_mode("eco")
memory.alloc("cache", 8)
let profile = memory.profile()
spark(profile["mode"])
spark(profile["allocated_mb"] > 0)
memory.free("cache")
"""
        result = run_source(source, filename="<test>", emit_stdout=False)
        self.assertEqual(result.output[0], "eco")
        self.assertEqual(result.output[1], "true")

    def test_class_object_lambda_and_typed_return(self) -> None:
        source = """
class Counter {
    forge init(start) {
        self.value = start
    }

    forge inc() -> number {
        self.value = self.value + 1
        return self.value
    }
}

let c = new Counter(10)
spark(c.inc())

let add = lambda(a, b) => a + b
spark(add(2, 3))
"""
        result = run_source(source, filename="main.ksharp", emit_stdout=False)
        self.assertEqual(result.output, ["11", "5"])

    def test_typed_return_raises_on_mismatch(self) -> None:
        source = """
forge bad() -> string {
    return 123
}
spark(bad())
"""
        with self.assertRaises(KSharpError):
            run_source(source, filename="main.ksharp", emit_stdout=False)

    def test_k_script_mode_blocks_use_import(self) -> None:
        source = """
use "libs/hello.ksharp"
"""
        with self.assertRaises(KSharpError):
            run_source(source, filename="lite.k", emit_stdout=False)

    def test_private_member_blocked_in_full_allowed_in_kpp(self) -> None:
        source = """
class Box {
    forge init(value) {
        self._value = value
    }
}
let box = new Box(42)
spark(box._value)
"""
        with self.assertRaises(KSharpError):
            run_source(source, filename="main.ksharp", emit_stdout=False)

        fast = run_source(source, filename="fast.kpp", emit_stdout=False)
        self.assertEqual(fast.output, ["42"])

    def test_runtime_error_includes_stack_trace(self) -> None:
        source = """
forge crash() {
    return 10 / 0
}
crash()
"""
        with self.assertRaises(KSharpError) as ctx:
            run_source(source, filename="main.ksharp", emit_stdout=False)
        text = str(ctx.exception)
        self.assertIn("StackTrace:", text)
        self.assertIn("crash", text)

    def test_adaptive_system_modules_and_anticheat(self) -> None:
        source = """
let profile = system.profile()
spark(profile["recommended_mode"])
spark(profile["tier"])

let bot = discord.create("!")
bot.command("ping", "pong")
spark(bot.simulate("!ping"))

anticheat.emit("speed_hack", "speed=999", 3)
let result = anticheat.detect(2)
spark(result["suspicious"])

let loop = game.create_loop(30)
forge update(dt, input) { return dt }
loop.on_update(update)
let stats = loop.run(0.01, 1)
spark(stats["frames"] >= 1)
"""
        result = run_source(source, filename="ecosystem.ksharp", emit_stdout=False)
        self.assertEqual(result.output[2], "pong")
        self.assertEqual(result.output[3], "true")
        self.assertEqual(result.output[4], "true")

    def test_package_project_init_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            created = init_project(project_root, name="demo")
            self.assertTrue(Path(created["config_path"]).exists())
            self.assertTrue((project_root / LOCAL_SITE_PACKAGES_REL).exists())

            config = load_project_config(project_root)
            self.assertEqual(config["name"], "demo")
            self.assertEqual(config["dependencies"], {})

            source_file = project_root / "main.ksharp"
            source_file.write_text('spark("ok")\n', encoding="utf-8")
            exit_code = kar_main(["build", str(project_root)])
            self.assertEqual(exit_code, 0)
            self.assertTrue((project_root / ".karship" / "build" / "build-manifest.json").exists())

    def test_discord_native_package_install_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            init_project(project_root, name="discord-native")

            installed = install_package(
                "discord.ksharp",
                project_root=project_root,
                global_install=False,
                install_python_bridge=False,
            )
            self.assertEqual(installed["package"], "discord-ksharp")
            library_path = project_root / "libs" / "discord.ksharp"
            self.assertTrue(library_path.exists())
            self.assertIn("discord_create", library_path.read_text(encoding="utf-8"))

            config = load_project_config(project_root)
            self.assertEqual(config["dependencies"]["discord-ksharp"], "native-0.1.0")

            removed = remove_package(
                "discord.ksharp",
                project_root=project_root,
                global_install=False,
                remove_python_bridge=False,
            )
            self.assertEqual(removed["package"], "discord-ksharp")
            self.assertFalse(library_path.exists())

    def test_ytdlp_native_package_install_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            init_project(project_root, name="ytdlp-native")

            installed = install_package(
                "ytdlp.ksharp",
                project_root=project_root,
                global_install=False,
                install_python_bridge=False,
            )
            self.assertEqual(installed["package"], "ytdlp-ksharp")
            library_path = project_root / "libs" / "ytdlp.ksharp"
            self.assertTrue(library_path.exists())
            self.assertIn("ytdlp_stream", library_path.read_text(encoding="utf-8"))

            config = load_project_config(project_root)
            self.assertEqual(config["dependencies"]["ytdlp-ksharp"], "native-0.1.0")

            removed = remove_package(
                "ytdlp.ksharp",
                project_root=project_root,
                global_install=False,
                remove_python_bridge=False,
            )
            self.assertEqual(removed["package"], "ytdlp-ksharp")
            self.assertFalse(library_path.exists())

    def test_discord_music_url_simulation(self) -> None:
        source = """
let bot = discord.create("!")
bot.music_url("play")
spark(bot.simulate("!play https://youtu.be/dQw4w9WgXcQ"))
"""
        result = run_source(source, filename="music-url.ksharp", emit_stdout=False)
        self.assertTrue(result.output[0].startswith("music-url-command:"))

    def test_native_package_catalog_is_large_and_useful(self) -> None:
        ids = native_package_ids()
        self.assertGreaterEqual(len(ids), 10)
        self.assertIn("web-ksharp", ids)
        self.assertIn("db-ksharp", ids)
        self.assertIn("utils-ksharp", ids)
        self.assertIn("collections-ksharp", ids)

    def test_install_and_remove_web_native_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            init_project(project_root, name="web-native")

            installed = install_package(
                "web.ksharp",
                project_root=project_root,
                global_install=False,
                install_python_bridge=False,
            )
            self.assertEqual(installed["package"], "web-ksharp")
            library_path = project_root / "libs" / "web.ksharp"
            self.assertTrue(library_path.exists())
            self.assertIn("forge web_route", library_path.read_text(encoding="utf-8"))

            config = load_project_config(project_root)
            self.assertEqual(config["dependencies"]["web-ksharp"], "native-0.1.0")

            removed = remove_package(
                "web.ksharp",
                project_root=project_root,
                global_install=False,
                remove_python_bridge=False,
            )
            self.assertEqual(removed["package"], "web-ksharp")
            self.assertFalse(library_path.exists())

    def test_discord_cookie_file_syncs_with_ytdlp_runtime(self) -> None:
        interpreter = Interpreter(output_stream=None, script_path="main.ksharp")
        bot = DiscordBotBridge(interpreter, prefix="!")
        ytdlp_runtime = interpreter.globals.get("ytdlp")

        bot.set_cookie_file("cookies.txt")
        self.assertEqual(ytdlp_runtime.profile()["cookie_file"], "cookies.txt")

        bot.clear_cookie_file()
        self.assertIsNone(ytdlp_runtime.profile()["cookie_file"])

    def test_ytdlp_stream_retries_after_first_failure(self) -> None:
        interpreter = Interpreter(output_stream=None, script_path="main.ksharp")
        module = YTDLPRuntimeModule(interpreter)
        attempts: list[str] = []
        fake_yt_dlp = types.SimpleNamespace(YoutubeDL=object)

        def _fake_extract(_yt_dlp: object, target: str, _options: dict[str, object]) -> object:
            attempts.append(target)
            if len(attempts) == 1:
                raise RuntimeError("temporary extraction error")
            return {
                "_type": "playlist",
                "entries": [
                    {
                        "title": "Lofi Stream",
                        "webpage_url": "https://youtube.com/watch?v=test",
                        "formats": [
                            {"acodec": "opus", "abr": 128, "url": "https://stream.example/audio"},
                        ],
                    }
                ],
            }

        with patch.dict(sys.modules, {"yt_dlp": fake_yt_dlp}):
            with patch.object(module, "_has_yt_dlp", return_value=True):
                with patch.object(module, "_extract_with_options", side_effect=_fake_extract):
                    payload = module.stream("lofi radio")

        self.assertEqual(payload["title"], "Lofi Stream")
        self.assertEqual(payload["stream_url"], "https://stream.example/audio")
        self.assertGreaterEqual(len(attempts), 2)
        self.assertIsNone(module.last_error())


if __name__ == "__main__":
    unittest.main()
