from __future__ import annotations

import ctypes
import gc
import hashlib
import hmac
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .ast_nodes import (
    Assign,
    Binary,
    BreakStmt,
    Call,
    ContinueStmt,
    EachStmt,
    Expr,
    ExprStmt,
    FunctionDecl,
    GetExpr,
    Grouping,
    IfStmt,
    IndexExpr,
    ListLiteral,
    Literal,
    Logical,
    Program,
    ReturnStmt,
    SparkStmt,
    Stmt,
    Unary,
    UseStmt,
    VarDecl,
    Variable,
    WhileStmt,
)

MODULE_EXTENSIONS = (".ksharp", ".kpp", ".k")
MB = 1024 * 1024


class KSharpRuntimeError(Exception):
    pass


class ReturnSignal(Exception):
    def __init__(self, value: Any) -> None:
        super().__init__()
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class MemoryManager:
    def __init__(self, preferred_mode: str | None = None) -> None:
        self.total_bytes = self.detect_total_memory_bytes()
        self.recommended_mode = self.recommend_mode(self.total_bytes)
        self.mode = self.recommended_mode
        self.allocations: dict[str, int] = {}
        self.last_gc_collected = 0
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
            if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
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
        raise KSharpRuntimeError(
            "Unknown memory mode. Use one of: eco, balanced, turbo."
        )

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
            raise KSharpRuntimeError("Memory block name cannot be empty.")
        if block in self.allocations:
            raise KSharpRuntimeError(f"Memory block '{block}' already exists.")

        try:
            size_mb = float(megabytes)
        except Exception as exc:
            raise KSharpRuntimeError("memory.alloc(name, mb) expects numeric mb.") from exc
        if size_mb <= 0:
            raise KSharpRuntimeError("Allocated size must be greater than 0 MB.")

        size_bytes = int(size_mb * MB)
        projected = self.allocated_bytes() + size_bytes
        if projected > self.cap_bytes:
            raise KSharpRuntimeError(
                "Memory reservation exceeds current profile cap "
                f"({self.cap_bytes / MB:.1f} MB). "
                "Use memory.set_mode('turbo') on high-end PCs or reserve less on low-end PCs."
            )

        self.allocations[block] = size_bytes
        return self.profile()

    def free(self, name: Any) -> float:
        block = str(name).strip()
        if block not in self.allocations:
            return 0.0
        released = self.allocations.pop(block)
        return round(released / MB, 3)

    def free_all(self) -> float:
        released = self.allocated_bytes()
        self.allocations.clear()
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
            "active_blocks": sorted(self.allocations.keys()),
            "last_gc_collected": self.last_gc_collected,
        }


class MemoryModule:
    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager

    def profile(self) -> dict[str, Any]:
        return self._manager.profile()

    def set_mode(self, mode: str) -> dict[str, Any]:
        return self._manager.set_mode(mode)

    def auto(self) -> dict[str, Any]:
        return self._manager.auto_mode()

    def alloc(self, name: str, megabytes: float) -> dict[str, Any]:
        return self._manager.alloc(name, megabytes)

    def free(self, name: str) -> float:
        return self._manager.free(name)

    def free_all(self) -> float:
        return self._manager.free_all()

    def gc(self) -> int:
        return self._manager.gc_collect()

    def mode(self) -> str:
        return self._manager.mode


class Environment:
    def __init__(self, parent: Environment | None = None) -> None:
        self.parent = parent
        self.values: dict[str, Any] = {}
        self.const_names: set[str] = set()

    def define(self, name: str, value: Any, is_const: bool = False) -> None:
        self.values[name] = value
        if is_const:
            self.const_names.add(name)

    def get(self, name: str) -> Any:
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise KSharpRuntimeError(f"Undefined variable '{name}'.")

    def assign(self, name: str, value: Any) -> None:
        if name in self.values:
            if name in self.const_names:
                raise KSharpRuntimeError(
                    f"Cannot reassign locked variable '{name}'. Use 'let' for mutable values."
                )
            self.values[name] = value
            return
        if self.parent is not None:
            self.parent.assign(name, value)
            return
        raise KSharpRuntimeError(f"Undefined variable '{name}'.")


@dataclass(slots=True)
class NativeFunction:
    name: str
    fn: Callable[..., Any]

    def __call__(self, *args: Any) -> Any:
        return self.fn(*args)

    def __repr__(self) -> str:
        return f"<native {self.name}>"


@dataclass(slots=True)
class KSharpFunction:
    declaration: FunctionDecl
    closure: Environment

    def call(self, interpreter: "Interpreter", args: list[Any]) -> Any:
        if len(args) != len(self.declaration.params):
            raise KSharpRuntimeError(
                f"Function '{self.declaration.name}' expects {len(self.declaration.params)}"
                f" args but got {len(args)}."
            )
        local_env = Environment(parent=self.closure)
        for param, value in zip(self.declaration.params, args, strict=True):
            local_env.define(param, value)
        try:
            interpreter.execute_block(self.declaration.body, local_env)
        except ReturnSignal as signal:
            return signal.value
        return None

    def __repr__(self) -> str:
        return f"<forge {self.declaration.name}>"


class SecurityModule:
    def hash(self, text: Any) -> str:
        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    def safe_equal(self, left: Any, right: Any) -> bool:
        return hmac.compare_digest(str(left), str(right))

    def white_hat_only(self) -> str:
        return "K# security mode: defensive and ethical use only."


class DBConnection:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def exec(self, sql: str, params: list[Any] | None = None) -> int:
        cur = self._conn.execute(sql, params or [])
        self._conn.commit()
        return cur.rowcount

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params or [])
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()


class DBModule:
    def open(self, path: str) -> DBConnection:
        return DBConnection(path)


class DiscordBotSim:
    def __init__(self, prefix: str = "!") -> None:
        self.prefix = prefix
        self._commands: dict[str, str] = {}

    def command(self, name: str, response: str) -> None:
        self._commands[name] = response

    def simulate(self, message: str) -> str:
        if not message.startswith(self.prefix):
            return ""
        command = message[len(self.prefix) :].strip().split(" ", maxsplit=1)[0]
        return self._commands.get(command, "unknown-command")


class DiscordModule:
    def create(self, prefix: str = "!") -> DiscordBotSim:
        return DiscordBotSim(prefix=prefix)


class SDKModule:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def to_json(self, value: Any) -> str:
        if self._memory_manager.mode == "eco":
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, ensure_ascii=False, indent=2)

    def from_json(self, text: str) -> Any:
        return json.loads(text)


class WebModule:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def page(self, title: str, body_html: str) -> str:
        compact = self._memory_manager.mode == "eco"
        space = "" if compact else " "
        return (
            "<!doctype html>"
            "<html><head><meta charset='utf-8'>"
            f"<title>{title}</title></head>{space}"
            f"<body>{body_html}</body></html>"
        )

    def json(self, value: Any) -> str:
        if self._memory_manager.mode == "eco":
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, ensure_ascii=False)


class Interpreter:
    def __init__(
        self,
        output_stream=None,
        *,
        script_path: str | None = None,
        module_roots: list[Path] | None = None,
        memory_mode: str | None = None,
    ) -> None:
        self.globals = Environment()
        self.environment = self.globals
        self.output_stream = output_stream
        self.output_lines: list[str] = []
        self.memory_manager = MemoryManager(preferred_mode=memory_mode)
        self.loaded_modules: set[Path] = set()
        self.loading_modules: set[Path] = set()
        self.current_script = self._normalize_script_path(script_path)
        self.module_roots = self._build_module_roots(module_roots)
        self._install_builtins()

    def _normalize_script_path(self, script_path: str | None) -> Path | None:
        if script_path is None:
            return None
        if script_path.startswith("<") and script_path.endswith(">"):
            return None
        return Path(script_path).resolve()

    def _build_module_roots(self, module_roots: list[Path] | None) -> list[Path]:
        roots: list[Path] = [Path.cwd().resolve()]
        if self.current_script is not None:
            roots.insert(0, self.current_script.parent.resolve())
        if module_roots:
            for root in module_roots:
                roots.append(Path(root).resolve())
        deduped: list[Path] = []
        for root in roots:
            if root not in deduped:
                deduped.append(root)
        return deduped

    def _install_builtins(self) -> None:
        self.globals.define("clock", NativeFunction("clock", lambda: time.time()), is_const=True)
        self.globals.define("len", NativeFunction("len", lambda value: len(value)), is_const=True)
        self.globals.define(
            "type_of", NativeFunction("type_of", lambda value: type(value).__name__), is_const=True
        )
        self.globals.define("to_int", NativeFunction("to_int", lambda value: int(value)), is_const=True)
        self.globals.define(
            "to_float", NativeFunction("to_float", lambda value: float(value)), is_const=True
        )
        self.globals.define("to_str", NativeFunction("to_str", lambda value: str(value)), is_const=True)
        self.globals.define(
            "range",
            NativeFunction(
                "range",
                lambda start, stop=None, step=1: (
                    range(int(start))
                    if stop is None
                    else range(int(start), int(stop), int(step))
                ),
            ),
            is_const=True,
        )
        self.globals.define("security", SecurityModule(), is_const=True)
        self.globals.define("db", DBModule(), is_const=True)
        self.globals.define("discord", DiscordModule(), is_const=True)
        self.globals.define("sdk", SDKModule(self.memory_manager), is_const=True)
        self.globals.define("web", WebModule(self.memory_manager), is_const=True)
        self.globals.define("memory", MemoryModule(self.memory_manager), is_const=True)
        self.globals.define(
            "use_lib",
            NativeFunction("use_lib", lambda module_path: self._execute_use_path(str(module_path))),
            is_const=True,
        )

    def interpret(self, program: Program) -> Any:
        last_value = None
        for statement in program.statements:
            result = self.execute(statement)
            if result is not None:
                last_value = result
        return last_value

    def execute(self, stmt: Stmt) -> Any:
        if isinstance(stmt, VarDecl):
            value = self.evaluate(stmt.initializer)
            self.environment.define(stmt.name, value, is_const=stmt.is_const)
            return None

        if isinstance(stmt, FunctionDecl):
            function = KSharpFunction(stmt, self.environment)
            self.environment.define(stmt.name, function, is_const=True)
            return None

        if isinstance(stmt, IfStmt):
            if self._is_truthy(self.evaluate(stmt.condition)):
                self.execute_block(stmt.then_branch, Environment(self.environment))
                return None
            for branch_condition, branch_body in stmt.elif_branches:
                if self._is_truthy(self.evaluate(branch_condition)):
                    self.execute_block(branch_body, Environment(self.environment))
                    return None
            if stmt.else_branch is not None:
                self.execute_block(stmt.else_branch, Environment(self.environment))
            return None

        if isinstance(stmt, WhileStmt):
            while self._is_truthy(self.evaluate(stmt.condition)):
                try:
                    self.execute_block(stmt.body, Environment(self.environment))
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return None

        if isinstance(stmt, EachStmt):
            iterable = self.evaluate(stmt.iterable)
            if not hasattr(iterable, "__iter__"):
                raise KSharpRuntimeError("Value used in each-loop is not iterable.")
            for item in iterable:
                loop_env = Environment(self.environment)
                loop_env.define(stmt.iterator_name, item)
                try:
                    self.execute_block(stmt.body, loop_env)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return None

        if isinstance(stmt, ReturnStmt):
            value = self.evaluate(stmt.value) if stmt.value is not None else None
            raise ReturnSignal(value)

        if isinstance(stmt, BreakStmt):
            raise BreakSignal()

        if isinstance(stmt, ContinueStmt):
            raise ContinueSignal()

        if isinstance(stmt, SparkStmt):
            rendered = " ".join(self.stringify(self.evaluate(arg)) for arg in stmt.args)
            self.output_lines.append(rendered)
            if self.output_stream is not None:
                print(rendered, file=self.output_stream)
            return None

        if isinstance(stmt, UseStmt):
            self._execute_use_path(stmt.module_path)
            return None

        if isinstance(stmt, ExprStmt):
            return self.evaluate(stmt.expr)

        raise KSharpRuntimeError(f"Unknown statement type: {type(stmt).__name__}")

    def execute_block(self, statements: list[Stmt], environment: Environment) -> None:
        previous = self.environment
        try:
            self.environment = environment
            for statement in statements:
                self.execute(statement)
        finally:
            self.environment = previous

    def _execute_use_path(self, module_ref: str) -> dict[str, Any]:
        module_path = self._resolve_module_path(module_ref)
        if module_path in self.loaded_modules:
            return {"module": str(module_path), "cached": True}
        if module_path in self.loading_modules:
            raise KSharpRuntimeError(
                f"Circular module import detected for '{module_path.name}'."
            )

        source = module_path.read_text(encoding="utf-8")
        from .lexer import Lexer
        from .parser import Parser

        self.loading_modules.add(module_path)
        previous_script = self.current_script
        previous_roots = list(self.module_roots)
        try:
            self.current_script = module_path
            if module_path.parent not in self.module_roots:
                self.module_roots.insert(0, module_path.parent)
            tokens = Lexer(source=source, filename=str(module_path)).tokenize()
            program = Parser(tokens=tokens, filename=str(module_path)).parse()
            for statement in program.statements:
                self.execute(statement)
            self.loaded_modules.add(module_path)
            return {"module": str(module_path), "cached": False}
        finally:
            self.loading_modules.discard(module_path)
            self.current_script = previous_script
            self.module_roots = previous_roots

    def _resolve_module_path(self, module_ref: str) -> Path:
        raw = module_ref.strip()
        if not raw:
            raise KSharpRuntimeError("use requires a non-empty module path.")

        raw_path = Path(raw)
        candidates: list[Path] = []
        if raw_path.suffix:
            candidates.append(raw_path)
        else:
            for ext in MODULE_EXTENSIONS:
                candidates.append(Path(f"{raw}{ext}"))

        search_dirs: list[Path] = []
        if self.current_script is not None:
            search_dirs.append(self.current_script.parent)
        search_dirs.extend(self.module_roots)
        if Path.cwd().resolve() not in search_dirs:
            search_dirs.append(Path.cwd().resolve())

        for candidate in candidates:
            if candidate.is_absolute():
                resolved = candidate.resolve()
                self._validate_module_path(resolved)
                if resolved.exists():
                    return resolved
                continue

            for base_dir in search_dirs:
                resolved = (base_dir / candidate).resolve()
                self._validate_module_path(resolved)
                if resolved.exists():
                    return resolved

        searched = ", ".join(str(path) for path in search_dirs)
        raise KSharpRuntimeError(
            f"Cannot find module '{module_ref}'. Searched in: {searched}"
        )

    def _validate_module_path(self, path: Path) -> None:
        if path.suffix not in MODULE_EXTENSIONS:
            raise KSharpRuntimeError(
                f"Unsupported module extension '{path.suffix}'. Use .ksharp, .kpp, or .k."
            )
        if not any(self._is_relative_to(path, root) for root in self.module_roots):
            raise KSharpRuntimeError(
                f"Module '{path}' is outside allowed roots for safety."
            )

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def evaluate(self, expr: Expr) -> Any:
        if isinstance(expr, Literal):
            return expr.value

        if isinstance(expr, Grouping):
            return self.evaluate(expr.expr)

        if isinstance(expr, Variable):
            return self.environment.get(expr.name)

        if isinstance(expr, Assign):
            value = self.evaluate(expr.value)
            self.environment.assign(expr.name, value)
            return value

        if isinstance(expr, ListLiteral):
            return [self.evaluate(item) for item in expr.elements]

        if isinstance(expr, Unary):
            right = self.evaluate(expr.right)
            if expr.operator in ("not", "!"):
                return not self._is_truthy(right)
            if expr.operator == "-":
                self._require_number(right, "Unary '-'")
                return -right
            raise KSharpRuntimeError(f"Unknown unary operator '{expr.operator}'.")

        if isinstance(expr, Logical):
            left = self.evaluate(expr.left)
            if expr.operator == "or":
                return left if self._is_truthy(left) else self.evaluate(expr.right)
            if expr.operator == "and":
                return self.evaluate(expr.right) if self._is_truthy(left) else left
            raise KSharpRuntimeError(f"Unknown logical operator '{expr.operator}'.")

        if isinstance(expr, Binary):
            left = self.evaluate(expr.left)
            right = self.evaluate(expr.right)
            return self._eval_binary(expr.operator, left, right)

        if isinstance(expr, Call):
            callee = self.evaluate(expr.callee)
            args = [self.evaluate(arg) for arg in expr.args]
            return self._call(callee, args)

        if isinstance(expr, GetExpr):
            target = self.evaluate(expr.target)
            return self._get_member(target, expr.name)

        if isinstance(expr, IndexExpr):
            target = self.evaluate(expr.target)
            index = self.evaluate(expr.index)
            return self._index(target, index)

        raise KSharpRuntimeError(f"Unknown expression type: {type(expr).__name__}")

    def _eval_binary(self, operator: str, left: Any, right: Any) -> Any:
        if operator == "+":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left + right
            return str(left) + str(right)
        if operator == "-":
            self._require_number(left, "'-'")
            self._require_number(right, "'-'")
            return left - right
        if operator == "*":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left * right
            if isinstance(left, str) and isinstance(right, int):
                return left * right
            raise KSharpRuntimeError("Operator '*' expects numbers or string*int.")
        if operator == "/":
            self._require_number(left, "'/'")
            self._require_number(right, "'/'")
            if right == 0:
                raise KSharpRuntimeError("Division by zero.")
            return left / right
        if operator == "%":
            self._require_number(left, "'%'")
            self._require_number(right, "'%'")
            return left % right
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        raise KSharpRuntimeError(f"Unknown binary operator '{operator}'.")

    def _call(self, callee: Any, args: list[Any]) -> Any:
        if isinstance(callee, KSharpFunction):
            return callee.call(self, args)
        if isinstance(callee, NativeFunction):
            try:
                return callee(*args)
            except TypeError as exc:
                raise KSharpRuntimeError(f"Invalid arguments for native function {callee.name}.") from exc
        if callable(callee):
            try:
                return callee(*args)
            except TypeError as exc:
                name = getattr(callee, "__name__", type(callee).__name__)
                raise KSharpRuntimeError(f"Invalid arguments for callable '{name}'.") from exc
        raise KSharpRuntimeError(f"Object of type '{type(callee).__name__}' is not callable.")

    def _index(self, target: Any, index: Any) -> Any:
        try:
            return target[index]
        except Exception as exc:
            raise KSharpRuntimeError(
                f"Cannot access index/key '{index}' on value of type '{type(target).__name__}'."
            ) from exc

    def _get_member(self, target: Any, name: str) -> Any:
        if name.startswith("_"):
            raise KSharpRuntimeError("Access to private members is blocked for safety.")
        if isinstance(target, dict):
            if name in target:
                return target[name]
            raise KSharpRuntimeError(f"Dictionary has no key '{name}'.")
        if hasattr(target, name):
            return getattr(target, name)
        raise KSharpRuntimeError(
            f"Value of type '{type(target).__name__}' has no member '{name}'."
        )

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        return bool(value)

    @staticmethod
    def _require_number(value: Any, context: str) -> None:
        if not isinstance(value, (int, float)):
            raise KSharpRuntimeError(f"{context} expects a numeric value, got {type(value).__name__}.")

    @staticmethod
    def stringify(value: Any) -> str:
        if value is None:
            return "nil"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, float):
            formatted = f"{value:.12g}"
            return formatted
        return str(value)
