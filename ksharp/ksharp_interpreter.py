from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from runtime.memory import MemoryRuntimeError

from .lexer import KSharpLexerError, Lexer
from .package_manager import configure_python_path_for_project, find_project_root
from .parser import KSharpParserError, Parser
from .runtime import Interpreter, KSharpRuntimeError


class KSharpError(Exception):
    pass


@dataclass(slots=True)
class ExecutionResult:
    value: Any
    output: list[str]


def infer_execution_mode(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".kpp"):
        return "performance"
    if lowered.endswith(".k"):
        return "script"
    return "full"


def compile_source(
    source: str,
    filename: str = "<memory>",
    execution_mode: str | None = None,
):
    mode = execution_mode or infer_execution_mode(filename)
    tokens = Lexer(source=source, filename=filename).tokenize()
    return Parser(tokens=tokens, filename=filename, execution_mode=mode).parse()


def run_source(
    source: str,
    *,
    filename: str = "<memory>",
    emit_stdout: bool = False,
    module_roots: list[str | Path] | None = None,
    memory_mode: str | None = None,
    execution_mode: str | None = None,
) -> ExecutionResult:
    try:
        project_root: Path | None = None
        if not (filename.startswith("<") and filename.endswith(">")):
            project_root = find_project_root(Path(filename).resolve().parent)
        configure_python_path_for_project(project_root)

        mode = execution_mode or infer_execution_mode(filename)
        program = compile_source(source, filename=filename, execution_mode=mode)
        interpreter = Interpreter(
            output_stream=None if not emit_stdout else sys.stdout,
            script_path=filename,
            module_roots=[Path(root) for root in module_roots] if module_roots else None,
            memory_mode=memory_mode,
            execution_mode=mode,
        )
        value = interpreter.interpret(program)
        return ExecutionResult(value=value, output=interpreter.output_lines)
    except (KSharpLexerError, KSharpParserError, KSharpRuntimeError, MemoryRuntimeError) as exc:
        raise KSharpError(str(exc)) from exc


def run_file(
    path: str | Path,
    *,
    emit_stdout: bool = True,
    module_roots: list[str | Path] | None = None,
    memory_mode: str | None = None,
    execution_mode: str | None = None,
) -> ExecutionResult:
    file_path = Path(path)
    source = file_path.read_text(encoding="utf-8")
    return run_source(
        source,
        filename=str(file_path),
        emit_stdout=emit_stdout,
        module_roots=module_roots,
        memory_mode=memory_mode,
        execution_mode=execution_mode,
    )
