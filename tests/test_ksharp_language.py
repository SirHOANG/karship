import unittest
from pathlib import Path
import tempfile

from ksharp.kar_cli import main as kar_main
from ksharp.ksharp_interpreter import KSharpError, run_file, run_source
from ksharp.package_manager import LOCAL_SITE_PACKAGES_REL, init_project, load_project_config


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


if __name__ == "__main__":
    unittest.main()
