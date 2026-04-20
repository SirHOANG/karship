from __future__ import annotations

import argparse
import pprint
import sys
from pathlib import Path

from .ksharp_interpreter import KSharpError, compile_source, run_file, run_source
from .lexer import Lexer


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksharp",
        description="Karship K# interpreter for .ksharp, .kpp and .k files.",
    )
    parser.add_argument("script", nargs="?", help="Script path with .ksharp/.kpp/.k extension.")
    parser.add_argument("--tokens", action="store_true", help="Print lexer tokens before execution.")
    parser.add_argument("--ast", action="store_true", help="Print parsed AST before execution.")
    parser.add_argument(
        "--memory-mode",
        choices=["auto", "eco", "balanced", "turbo"],
        default="auto",
        help="Memory profile: auto detects PC strength, eco for weak PCs, turbo for high-end.",
    )
    return parser


def _print_tokens(script_path: str, source: str) -> None:
    for token in Lexer(source=source, filename=script_path).tokenize():
        print(token)


def _print_ast(script_path: str, source: str) -> None:
    ast = compile_source(source, filename=script_path)
    pprint.pprint(ast)


def _run_repl() -> int:
    print("Karship K# REPL. Type :quit to exit.")
    while True:
        try:
            line = input("k#> ")
        except EOFError:
            print()
            return 0
        if not line.strip():
            continue
        if line.strip() == ":quit":
            return 0
        try:
            result = run_source(line, filename="<repl>", emit_stdout=True)
            if result.value is not None:
                print(result.value)
        except KSharpError as exc:
            print(exc, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.script:
        return _run_repl()

    script_path = str(Path(args.script))
    if not script_path.endswith((".ksharp", ".kpp", ".k")):
        print(
            "Warning: expected .ksharp, .kpp, or .k extension. Executing anyway.",
            file=sys.stderr,
        )

    try:
        source = Path(script_path).read_text(encoding="utf-8")
        if args.tokens:
            _print_tokens(script_path, source)
        if args.ast:
            _print_ast(script_path, source)
        run_file(
            script_path,
            emit_stdout=True,
            memory_mode=None if args.memory_mode == "auto" else args.memory_mode,
        )
        return 0
    except FileNotFoundError:
        print(f"File not found: {script_path}", file=sys.stderr)
        return 1
    except KSharpError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
