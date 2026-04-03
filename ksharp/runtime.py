from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from runtime.memory import MemoryManager, MemoryModule, MemoryRuntimeError
from runtime.monitor import RuntimeMonitor
from runtime.system_detection import HardwareProfile, SystemDetector

from .package_manager import get_global_karship_packages_dir
from .modules import (
    AntiCheatRuntimeModule,
    DiscordRuntimeModule,
    GameRuntimeModule,
    SecurityRuntimeModule,
    WebRuntimeModule,
    YTDLPRuntimeModule,
)
from .ast_nodes import (
    Assign,
    Binary,
    BreakStmt,
    Call,
    ClassDecl,
    ContinueStmt,
    EachStmt,
    Expr,
    ExprStmt,
    FunctionDecl,
    GetExpr,
    Grouping,
    IfStmt,
    IndexExpr,
    LambdaExpr,
    ListLiteral,
    Literal,
    Logical,
    NewExpr,
    Program,
    ReturnStmt,
    SetExpr,
    SparkStmt,
    Stmt,
    Unary,
    UseStmt,
    VarDecl,
    Variable,
    WhileStmt,
)

MODULE_EXTENSIONS = (".ksharp", ".kpp", ".k")


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
    is_initializer: bool = False

    def bind(self, instance: "KSharpInstance") -> "KSharpFunction":
        method_env = Environment(parent=self.closure)
        method_env.define("self", instance, is_const=True)
        return KSharpFunction(
            declaration=self.declaration,
            closure=method_env,
            is_initializer=self.is_initializer,
        )

    def call(self, interpreter: "Interpreter", args: list[Any]) -> Any:
        if len(args) != len(self.declaration.params):
            raise interpreter.runtime_error(
                f"Function '{self.declaration.name}' expects {len(self.declaration.params)} "
                f"args but got {len(args)}."
            )

        local_env = Environment(parent=self.closure)
        for param, value in zip(self.declaration.params, args, strict=True):
            local_env.define(param, value)

        interpreter.push_call(self.declaration.name)
        try:
            return_value: Any = None
            try:
                interpreter.execute_block(self.declaration.body, local_env)
            except ReturnSignal as signal:
                return_value = signal.value

            if self.is_initializer:
                return self.closure.get("self")

            if (
                interpreter.strict_safety
                and self.declaration.return_type is not None
            ):
                interpreter.enforce_return_type(
                    self.declaration.name,
                    self.declaration.return_type,
                    return_value,
                )
            return return_value
        finally:
            interpreter.pop_call()

    def __repr__(self) -> str:
        return f"<forge {self.declaration.name}>"


@dataclass(slots=True)
class KSharpLambda:
    params: list[str]
    body: Expr
    closure: Environment

    def call(self, interpreter: "Interpreter", args: list[Any]) -> Any:
        if len(args) != len(self.params):
            raise interpreter.runtime_error(
                f"Lambda expects {len(self.params)} args but got {len(args)}."
            )

        local_env = Environment(parent=self.closure)
        for param, value in zip(self.params, args, strict=True):
            local_env.define(param, value)

        interpreter.push_call("<lambda>")
        try:
            previous = interpreter.environment
            try:
                interpreter.environment = local_env
                return interpreter.evaluate(self.body)
            finally:
                interpreter.environment = previous
        finally:
            interpreter.pop_call()

    def __repr__(self) -> str:
        return "<lambda>"


@dataclass(slots=True)
class KSharpClass:
    name: str
    methods: dict[str, KSharpFunction]

    def find_method(self, name: str) -> KSharpFunction | None:
        return self.methods.get(name)

    def call(self, interpreter: "Interpreter", args: list[Any]) -> "KSharpInstance":
        instance = KSharpInstance(self)
        initializer = self.find_method("init")
        if initializer is not None:
            initializer.bind(instance).call(interpreter, args)
        elif args and interpreter.strict_safety:
            raise interpreter.runtime_error(
                f"Class '{self.name}' has no init method but received constructor args."
            )
        return instance

    def __repr__(self) -> str:
        return f"<class {self.name}>"


class KSharpInstance:
    def __init__(self, klass: KSharpClass) -> None:
        self.klass = klass
        self.fields: dict[str, Any] = {}

    def get(self, name: str, interpreter: "Interpreter") -> Any:
        if name in self.fields:
            return self.fields[name]
        method = self.klass.find_method(name)
        if method is not None:
            return method.bind(self)
        raise interpreter.runtime_error(
            f"Class '{self.klass.name}' has no property or method '{name}'."
        )

    def set(self, name: str, value: Any) -> Any:
        self.fields[name] = value
        return value

    def __repr__(self) -> str:
        return f"<{self.klass.name} instance>"


class SystemRuntimeModule:
    def __init__(
        self,
        *,
        detector: SystemDetector,
        hardware_profile: HardwareProfile,
        runtime_monitor: RuntimeMonitor,
        memory_manager: MemoryManager,
        execution_mode: str,
        strict_safety: bool,
    ) -> None:
        self._detector = detector
        self._profile = hardware_profile
        self._runtime_monitor = runtime_monitor
        self._memory_manager = memory_manager
        self._execution_mode = execution_mode
        self._strict_safety = strict_safety

    def profile(self) -> dict[str, Any]:
        payload = self._profile.as_dict()
        payload["execution_mode"] = self._execution_mode
        payload["strict_safety"] = self._strict_safety
        payload["active_memory_mode"] = self._memory_manager.mode
        return payload

    def refresh(self) -> dict[str, Any]:
        self._profile = self._detector.detect()
        return self.profile()

    def tier(self) -> str:
        return self._profile.tier

    def recommended_mode(self) -> str:
        return self._profile.recommended_mode

    def recommended_concurrency(self) -> int:
        return self._profile.recommended_concurrency

    def monitor(self) -> dict[str, Any]:
        return self._runtime_monitor.profile()

    def memory(self) -> dict[str, Any]:
        return self._memory_manager.profile()

    def warnings(self) -> list[str]:
        monitor_warnings = self._runtime_monitor.profile()["warnings"]
        memory_warnings = self._memory_manager.profile()["warnings"]
        return list(memory_warnings) + list(monitor_warnings)

    def doctor(self) -> dict[str, Any]:
        return {
            "hardware": self.profile(),
            "memory": self.memory(),
            "monitor": self.monitor(),
            "status": "ok",
        }


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


class SDKModule:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def to_json(self, value: Any) -> str:
        if self._memory_manager.mode == "eco":
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, ensure_ascii=False, indent=2)

    def from_json(self, text: str) -> Any:
        return json.loads(text)


class Interpreter:
    def __init__(
        self,
        output_stream=None,
        *,
        script_path: str | None = None,
        module_roots: list[Path] | None = None,
        memory_mode: str | None = None,
        execution_mode: str | None = None,
    ) -> None:
        self.output_stream = output_stream
        self.output_lines: list[str] = []
        self.call_stack: list[str] = []

        self.current_script = self.normalize_script_path(script_path)
        self.execution_mode = execution_mode or self.mode_from_path(script_path)
        self.strict_safety = self.execution_mode != "performance"

        self.system_detector = SystemDetector()
        self.hardware_profile = self.system_detector.detect()
        resolved_memory_mode = memory_mode or self.hardware_profile.recommended_mode
        self.memory_manager = MemoryManager(
            preferred_mode=resolved_memory_mode,
            strict_checks=self.strict_safety,
        )
        self.runtime_monitor = RuntimeMonitor(
            execution_mode=self.execution_mode,
            tier=self.hardware_profile.tier,
            strict_safety=self.strict_safety,
        )

        self.globals = Environment()
        self.environment = self.globals
        self.loaded_modules: set[Path] = set()
        self.loading_modules: set[Path] = set()
        self.module_roots = self.build_module_roots(module_roots)
        self.install_builtins()

    def normalize_script_path(self, script_path: str | None) -> Path | None:
        if script_path is None:
            return None
        if script_path.startswith("<") and script_path.endswith(">"):
            return None
        return Path(script_path).resolve()

    def build_module_roots(self, module_roots: list[Path] | None) -> list[Path]:
        roots: list[Path] = [Path.cwd().resolve()]
        if self.current_script is not None:
            roots.insert(0, self.current_script.parent.resolve())
        if module_roots:
            for root in module_roots:
                roots.append(Path(root).resolve())

        expanded_roots: list[Path] = []
        for root in roots:
            expanded_roots.append(root)
            local_libs = (root / "libs").resolve()
            if local_libs.exists():
                expanded_roots.append(local_libs)

        global_packages = get_global_karship_packages_dir(create=False)
        if global_packages.exists():
            expanded_roots.append(global_packages.resolve())

        deduped: list[Path] = []
        for root in expanded_roots:
            if root not in deduped:
                deduped.append(root)
        return deduped

    def install_builtins(self) -> None:
        self.globals.define("clock", NativeFunction("clock", lambda: time.time()), is_const=True)
        self.globals.define("len", NativeFunction("len", lambda value: len(value)), is_const=True)
        self.globals.define(
            "type_of",
            NativeFunction("type_of", lambda value: type(value).__name__),
            is_const=True,
        )
        self.globals.define("to_int", NativeFunction("to_int", lambda value: int(value)), is_const=True)
        self.globals.define(
            "to_float",
            NativeFunction("to_float", lambda value: float(value)),
            is_const=True,
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

        self.globals.define("security", SecurityRuntimeModule(), is_const=True)
        self.globals.define("db", DBModule(), is_const=True)
        self.globals.define("discord", DiscordRuntimeModule(self), is_const=True)
        self.globals.define(
            "game",
            GameRuntimeModule(
                self,
                default_fps=30 if self.hardware_profile.tier == "low" else 60,
            ),
            is_const=True,
        )
        self.globals.define("sdk", SDKModule(self.memory_manager), is_const=True)
        self.globals.define(
            "web",
            WebRuntimeModule(self, self.memory_manager),
            is_const=True,
        )
        self.globals.define(
            "anticheat",
            AntiCheatRuntimeModule(self, self.memory_manager),
            is_const=True,
        )
        self.globals.define("ytdlp", YTDLPRuntimeModule(self), is_const=True)
        self.globals.define(
            "system",
            SystemRuntimeModule(
                detector=self.system_detector,
                hardware_profile=self.hardware_profile,
                runtime_monitor=self.runtime_monitor,
                memory_manager=self.memory_manager,
                execution_mode=self.execution_mode,
                strict_safety=self.strict_safety,
            ),
            is_const=True,
        )

        allow_memory_mutation = self.execution_mode != "script"
        self.globals.define(
            "memory",
            MemoryModule(self.memory_manager, allow_mutation=allow_memory_mutation),
            is_const=True,
        )
        self.globals.define(
            "use_lib",
            NativeFunction("use_lib", lambda module_path: self.execute_use_path(str(module_path))),
            is_const=True,
        )

    def push_call(self, name: str) -> None:
        self.call_stack.append(name)

    def pop_call(self) -> None:
        if self.call_stack:
            self.call_stack.pop()

    def format_stack_trace(self) -> str:
        if not self.call_stack:
            return "<global>"
        return " -> ".join(self.call_stack)

    def runtime_error(self, message: str) -> KSharpRuntimeError:
        return KSharpRuntimeError(f"{message}\nStackTrace: {self.format_stack_trace()}")

    def runtime_tick(self) -> None:
        monitor_state = self.runtime_monitor.tick()
        warnings = monitor_state.get("warnings", [])
        for warning in warnings:
            self.memory_manager.warning_messages.append(f"monitor: {warning}")
        hard_limit_hit = any("hard limit" in str(item).lower() for item in warnings)
        if hard_limit_hit and self.strict_safety:
            raise self.runtime_error(
                "Runtime halted because process memory exceeded hard safety limit."
            )

    def mode_from_path(self, script_path: str | None) -> str:
        if script_path is None:
            return "full"
        lower = script_path.lower()
        if lower.endswith(".kpp"):
            return "performance"
        if lower.endswith(".k"):
            return "script"
        return "full"

    def interpret(self, program: Program) -> Any:
        last_value = None
        try:
            for statement in program.statements:
                result = self.execute(statement)
                if result is not None:
                    last_value = result
            return last_value
        except MemoryRuntimeError as exc:
            raise self.runtime_error(str(exc)) from exc
        except KSharpRuntimeError as exc:
            if "StackTrace:" in str(exc):
                raise
            raise self.runtime_error(str(exc)) from exc

    def execute(self, stmt: Stmt) -> Any:
        self.runtime_tick()
        if isinstance(stmt, VarDecl):
            value = self.evaluate(stmt.initializer)
            self.environment.define(stmt.name, value, is_const=stmt.is_const)
            return None

        if isinstance(stmt, FunctionDecl):
            function = KSharpFunction(stmt, self.environment)
            self.environment.define(stmt.name, function, is_const=True)
            return None

        if isinstance(stmt, ClassDecl):
            if self.execution_mode == "script":
                raise self.runtime_error("class is disabled in .k scripting mode.")
            methods: dict[str, KSharpFunction] = {}
            for method_decl in stmt.methods:
                methods[method_decl.name] = KSharpFunction(
                    declaration=method_decl,
                    closure=self.environment,
                    is_initializer=method_decl.name == "init",
                )
            klass = KSharpClass(stmt.name, methods)
            self.environment.define(stmt.name, klass, is_const=True)
            return None

        if isinstance(stmt, IfStmt):
            if self.is_truthy(self.evaluate(stmt.condition)):
                self.execute_block(stmt.then_branch, Environment(self.environment))
                return None
            for branch_condition, branch_body in stmt.elif_branches:
                if self.is_truthy(self.evaluate(branch_condition)):
                    self.execute_block(branch_body, Environment(self.environment))
                    return None
            if stmt.else_branch is not None:
                self.execute_block(stmt.else_branch, Environment(self.environment))
            return None

        if isinstance(stmt, WhileStmt):
            while self.is_truthy(self.evaluate(stmt.condition)):
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
                raise self.runtime_error("Value used in each-loop is not iterable.")
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
            if self.execution_mode == "script":
                raise self.runtime_error("use/import is disabled in lightweight .k mode.")
            self.execute_use_path(stmt.module_path)
            return None

        if isinstance(stmt, ExprStmt):
            return self.evaluate(stmt.expr)

        raise self.runtime_error(f"Unknown statement type: {type(stmt).__name__}")

    def execute_block(self, statements: list[Stmt], environment: Environment) -> None:
        previous = self.environment
        try:
            self.environment = environment
            for statement in statements:
                self.execute(statement)
        finally:
            self.environment = previous

    def execute_use_path(self, module_ref: str) -> dict[str, Any]:
        module_path = self.resolve_module_path(module_ref)
        if module_path in self.loaded_modules:
            return {"module": str(module_path), "cached": True}
        if module_path in self.loading_modules:
            raise self.runtime_error(f"Circular module import detected for '{module_path.name}'.")

        from .lexer import Lexer
        from .parser import Parser

        source = module_path.read_text(encoding="utf-8")
        imported_mode = self.mode_from_path(str(module_path))

        self.loading_modules.add(module_path)
        previous_script = self.current_script
        previous_roots = list(self.module_roots)
        try:
            self.current_script = module_path
            if module_path.parent not in self.module_roots:
                self.module_roots.insert(0, module_path.parent)
            tokens = Lexer(source=source, filename=str(module_path)).tokenize()
            program = Parser(
                tokens=tokens,
                filename=str(module_path),
                execution_mode=imported_mode,
            ).parse()
            for statement in program.statements:
                self.execute(statement)
            self.loaded_modules.add(module_path)
            return {"module": str(module_path), "cached": False}
        finally:
            self.loading_modules.discard(module_path)
            self.current_script = previous_script
            self.module_roots = previous_roots

    def resolve_module_path(self, module_ref: str) -> Path:
        raw = module_ref.strip()
        if not raw:
            raise self.runtime_error("use requires a non-empty module path.")

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
        cwd = Path.cwd().resolve()
        if cwd not in search_dirs:
            search_dirs.append(cwd)

        for candidate in candidates:
            if candidate.is_absolute():
                resolved = candidate.resolve()
                self.validate_module_path(resolved)
                if resolved.exists():
                    return resolved
                continue

            for base_dir in search_dirs:
                resolved = (base_dir / candidate).resolve()
                self.validate_module_path(resolved)
                if resolved.exists():
                    return resolved

        searched = ", ".join(str(path) for path in search_dirs)
        raise self.runtime_error(f"Cannot find module '{module_ref}'. Searched in: {searched}")

    def validate_module_path(self, path: Path) -> None:
        if path.suffix not in MODULE_EXTENSIONS:
            raise self.runtime_error(
                f"Unsupported module extension '{path.suffix}'. Use .ksharp, .kpp, or .k."
            )
        if self.strict_safety and not any(self.is_relative_to(path, root) for root in self.module_roots):
            raise self.runtime_error(f"Module '{path}' is outside allowed roots for safety.")

    @staticmethod
    def is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def evaluate(self, expr: Expr) -> Any:
        self.runtime_tick()
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

        if isinstance(expr, SetExpr):
            target = self.evaluate(expr.target)
            value = self.evaluate(expr.value)
            return self.set_member(target, expr.name, value)

        if isinstance(expr, ListLiteral):
            return [self.evaluate(item) for item in expr.elements]

        if isinstance(expr, LambdaExpr):
            return KSharpLambda(params=expr.params, body=expr.body, closure=self.environment)

        if isinstance(expr, NewExpr):
            class_obj = self.environment.get(expr.class_name)
            if not isinstance(class_obj, KSharpClass):
                raise self.runtime_error(f"'{expr.class_name}' is not a class.")
            args = [self.evaluate(arg) for arg in expr.args]
            return class_obj.call(self, args)

        if isinstance(expr, Unary):
            right = self.evaluate(expr.right)
            if expr.operator in ("not", "!"):
                return not self.is_truthy(right)
            if expr.operator == "-":
                self.require_number(right, "Unary '-'")
                return -right
            raise self.runtime_error(f"Unknown unary operator '{expr.operator}'.")

        if isinstance(expr, Logical):
            left = self.evaluate(expr.left)
            if expr.operator == "or":
                return left if self.is_truthy(left) else self.evaluate(expr.right)
            if expr.operator == "and":
                return self.evaluate(expr.right) if self.is_truthy(left) else left
            raise self.runtime_error(f"Unknown logical operator '{expr.operator}'.")

        if isinstance(expr, Binary):
            left = self.evaluate(expr.left)
            right = self.evaluate(expr.right)
            return self.eval_binary(expr.operator, left, right)

        if isinstance(expr, Call):
            callee = self.evaluate(expr.callee)
            args = [self.evaluate(arg) for arg in expr.args]
            return self.call(callee, args)

        if isinstance(expr, GetExpr):
            target = self.evaluate(expr.target)
            return self.get_member(target, expr.name)

        if isinstance(expr, IndexExpr):
            target = self.evaluate(expr.target)
            index = self.evaluate(expr.index)
            return self.index(target, index)

        raise self.runtime_error(f"Unknown expression type: {type(expr).__name__}")

    def eval_binary(self, operator: str, left: Any, right: Any) -> Any:
        if operator == "+":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left + right
            return str(left) + str(right)
        if operator == "-":
            self.require_number(left, "'-'")
            self.require_number(right, "'-'")
            return left - right
        if operator == "*":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left * right
            if isinstance(left, str) and isinstance(right, int):
                return left * right
            raise self.runtime_error("Operator '*' expects numbers or string*int.")
        if operator == "/":
            self.require_number(left, "'/'")
            self.require_number(right, "'/'")
            if right == 0:
                raise self.runtime_error("Division by zero.")
            return left / right
        if operator == "%":
            self.require_number(left, "'%'")
            self.require_number(right, "'%'")
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
        raise self.runtime_error(f"Unknown binary operator '{operator}'.")

    def call(self, callee: Any, args: list[Any]) -> Any:
        if isinstance(callee, KSharpFunction):
            return callee.call(self, args)
        if isinstance(callee, KSharpLambda):
            return callee.call(self, args)
        if isinstance(callee, KSharpClass):
            return callee.call(self, args)
        if isinstance(callee, NativeFunction):
            try:
                return callee(*args)
            except Exception as exc:
                raise self.runtime_error(
                    f"Invalid arguments for native function '{callee.name}'."
                ) from exc
        if callable(callee):
            try:
                return callee(*args)
            except Exception as exc:
                name = getattr(callee, "__name__", type(callee).__name__)
                raise self.runtime_error(f"Invalid arguments for callable '{name}'.") from exc
        raise self.runtime_error(f"Object of type '{type(callee).__name__}' is not callable.")

    def index(self, target: Any, index: Any) -> Any:
        try:
            return target[index]
        except Exception as exc:
            raise self.runtime_error(
                f"Cannot access index/key '{index}' on value of type '{type(target).__name__}'."
            ) from exc

    def get_member(self, target: Any, name: str) -> Any:
        if self.strict_safety and name.startswith("_"):
            raise self.runtime_error("Access to private members is blocked for safety.")
        if isinstance(target, KSharpInstance):
            return target.get(name, self)
        if isinstance(target, dict):
            if name in target:
                return target[name]
            raise self.runtime_error(f"Dictionary has no key '{name}'.")
        if hasattr(target, name):
            return getattr(target, name)
        raise self.runtime_error(f"Value of type '{type(target).__name__}' has no member '{name}'.")

    def set_member(self, target: Any, name: str, value: Any) -> Any:
        if self.strict_safety and name.startswith("_"):
            raise self.runtime_error("Setting private members is blocked for safety.")
        if isinstance(target, KSharpInstance):
            return target.set(name, value)
        if isinstance(target, dict):
            target[name] = value
            return value
        if hasattr(target, name):
            setattr(target, name, value)
            return value
        raise self.runtime_error(
            f"Cannot set member '{name}' on value of type '{type(target).__name__}'."
        )

    def enforce_return_type(self, func_name: str, expected_type: str, value: Any) -> None:
        normalized = expected_type.strip().lower()
        if normalized in ("any", "object"):
            return
        valid = False
        if normalized in ("int", "integer"):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif normalized in ("float", "double"):
            valid = isinstance(value, float)
        elif normalized in ("number", "num"):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif normalized in ("str", "string"):
            valid = isinstance(value, str)
        elif normalized in ("bool", "boolean"):
            valid = isinstance(value, bool)
        elif normalized in ("list", "array"):
            valid = isinstance(value, list)
        elif normalized in ("dict", "map"):
            valid = isinstance(value, dict)
        elif normalized in ("nil", "void", "none"):
            valid = value is None
        elif normalized in ("class", "instance"):
            valid = isinstance(value, KSharpInstance)
        else:
            # Unknown type hints are treated as documentation-only for now.
            return

        if not valid:
            raise self.runtime_error(
                f"Return type mismatch in '{func_name}': expected {expected_type}, got {type(value).__name__}."
            )

    @staticmethod
    def is_truthy(value: Any) -> bool:
        return bool(value)

    def require_number(self, value: Any, context: str) -> None:
        if not isinstance(value, (int, float)):
            raise self.runtime_error(
                f"{context} expects a numeric value, got {type(value).__name__}."
            )

    @staticmethod
    def stringify(value: Any) -> str:
        if value is None:
            return "nil"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, float):
            return f"{value:.12g}"
        return str(value)
