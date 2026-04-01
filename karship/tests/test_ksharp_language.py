import unittest
from pathlib import Path
import tempfile

from ksharp.ksharp_interpreter import KSharpError, run_file, run_source


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


if __name__ == "__main__":
    unittest.main()
