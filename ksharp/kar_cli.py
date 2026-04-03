from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from runtime.system_detection import SystemDetector

from . import __version__
from .ksharp_interpreter import KSharpError, compile_source, infer_execution_mode, run_file
from .package_manager import (
    CONFIG_FILENAME,
    PackageManagerError,
    configure_python_path_for_project,
    find_project_root,
    init_project,
    install_package,
    load_project_config,
    remove_package,
)
from .runtime import Interpreter

SOURCE_EXTENSIONS = (".ksharp", ".kpp", ".k")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kar",
        description="Karship K# ecosystem CLI",
    )
    parser.add_argument("--version", action="store_true", help="Show Karship version and exit.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a Karship source file.")
    run_parser.add_argument("script", help="Path to a .ksharp/.kpp/.k script.")
    run_parser.add_argument(
        "--memory-mode",
        choices=["auto", "eco", "balanced", "turbo"],
        default="auto",
        help="Override adaptive memory mode.",
    )

    build_parser = subparsers.add_parser("build", help="Parse/validate project source and generate build manifest.")
    build_parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="File or directory to build (default: current directory).",
    )

    subparsers.add_parser("mem", help="Show adaptive hardware + memory profile.")
    subparsers.add_parser("doctor", help="Run diagnostics for Karship runtime and environment.")

    init_parser = subparsers.add_parser("init", help="Create a new Karship project.")
    init_parser.add_argument("path", nargs="?", default=".", help="Project directory.")
    init_parser.add_argument("--name", help="Project name for karship.json.")

    install_parser = subparsers.add_parser("install", help="Install a package (local by default).")
    install_parser.add_argument("package", help="Package name to install.")
    install_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install into global Python environment instead of local project.",
    )
    install_parser.add_argument(
        "--project",
        help=f"Project root path containing {CONFIG_FILENAME}.",
    )

    remove_parser = subparsers.add_parser("remove", help="Remove a package (local by default).")
    remove_parser.add_argument("package", help="Package name to remove.")
    remove_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Remove from global Python environment instead of local project.",
    )
    remove_parser.add_argument(
        "--project",
        help=f"Project root path containing {CONFIG_FILENAME}.",
    )

    return parser


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _collect_source_files(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() not in SOURCE_EXTENSIONS:
            raise PackageManagerError(
                f"Unsupported source extension '{target.suffix}'. Use .ksharp/.kpp/.k."
            )
        return [target.resolve()]

    if not target.exists():
        raise PackageManagerError(f"Build target does not exist: {target}")

    skip_dirs = {".karship", ".git", "__pycache__", "node_modules"}
    files: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        files.append(path.resolve())
    return sorted(files)


def _resolve_project_root_for_command(
    *,
    explicit_project: str | None = None,
    script_hint: Path | None = None,
) -> Path | None:
    if explicit_project:
        return Path(explicit_project).resolve()
    if script_hint is not None:
        return find_project_root(script_hint.parent)
    return find_project_root()


def command_run(args: argparse.Namespace) -> int:
    script_path = Path(args.script).resolve()
    if not script_path.exists():
        print(f"File not found: {script_path}", file=sys.stderr)
        return 1

    project_root = _resolve_project_root_for_command(script_hint=script_path)
    configure_python_path_for_project(project_root)

    try:
        run_file(
            script_path,
            emit_stdout=True,
            memory_mode=None if args.memory_mode == "auto" else args.memory_mode,
        )
        return 0
    except KSharpError as exc:
        print(exc, file=sys.stderr)
        return 1


def command_build(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    project_root = _resolve_project_root_for_command(
        script_hint=target if target.is_file() else None
    ) or (target.parent if target.is_file() else target)

    try:
        files = _collect_source_files(target)
    except PackageManagerError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not files:
        print("No Karship source files found for build.", file=sys.stderr)
        return 1

    compiled: list[str] = []
    errors: list[dict[str, str]] = []
    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8")
            compile_source(
                source=source,
                filename=str(file_path),
                execution_mode=infer_execution_mode(str(file_path)),
            )
            compiled.append(str(file_path))
        except Exception as exc:
            errors.append({"file": str(file_path), "error": str(exc)})

    build_dir = project_root / ".karship" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = build_dir / "build-manifest.json"
    manifest = {
        "built_at_epoch": round(time.time(), 3),
        "project_root": str(project_root),
        "compiled_count": len(compiled),
        "error_count": len(errors),
        "files": compiled,
        "errors": errors,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _emit_json({"manifest": str(manifest_path), **manifest})
    return 0 if not errors else 1


def command_mem() -> int:
    interpreter = Interpreter(script_path="<kar-mem>", execution_mode="full")
    payload = {
        "hardware": interpreter.hardware_profile.as_dict(),
        "memory": interpreter.memory_manager.profile(),
        "monitor": interpreter.runtime_monitor.profile(),
    }
    _emit_json(payload)
    return 0


def command_doctor() -> int:
    detector = SystemDetector()
    hardware = detector.detect().as_dict()
    checks = {
        "python_version": sys.version.split(" ")[0],
        "platform": platform.platform(),
        "config_found": find_project_root() is not None,
    }
    optional_modules = ["psutil", "discord", "requests"]
    module_status: dict[str, bool] = {}
    for mod_name in optional_modules:
        try:
            __import__(mod_name)
            module_status[mod_name] = True
        except Exception:
            module_status[mod_name] = False

    payload = {
        "status": "ok",
        "checks": checks,
        "optional_modules": module_status,
        "hardware": hardware,
    }
    _emit_json(payload)
    return 0


def command_init(args: argparse.Namespace) -> int:
    try:
        result = init_project(args.path, name=args.name)
        _emit_json({"status": "created", **result})
        return 0
    except PackageManagerError as exc:
        print(exc, file=sys.stderr)
        return 1


def command_install(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root_for_command(explicit_project=args.project)
    if not args.global_install and project_root is None:
        print(
            f"Local install requires {CONFIG_FILENAME}. Run 'kar init' first.",
            file=sys.stderr,
        )
        return 1

    try:
        if project_root is not None and (project_root / CONFIG_FILENAME).exists():
            load_project_config(project_root)
        result = install_package(
            args.package,
            project_root=project_root,
            global_install=bool(args.global_install),
        )
        _emit_json({"status": "installed", **result})
        return 0
    except PackageManagerError as exc:
        print(exc, file=sys.stderr)
        return 1


def command_remove(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root_for_command(explicit_project=args.project)
    if not args.global_install and project_root is None:
        print(
            f"Local remove requires {CONFIG_FILENAME}. Run inside a Karship project.",
            file=sys.stderr,
        )
        return 1

    try:
        if project_root is not None and (project_root / CONFIG_FILENAME).exists():
            load_project_config(project_root)
        result = remove_package(
            args.package,
            project_root=project_root,
            global_install=bool(args.global_install),
        )
        _emit_json({"status": "removed", **result})
        return 0
    except PackageManagerError as exc:
        print(exc, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"karship-ksharp {__version__}")
        if args.command is None:
            return 0

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        return command_run(args)
    if args.command == "build":
        return command_build(args)
    if args.command == "mem":
        return command_mem()
    if args.command == "doctor":
        return command_doctor()
    if args.command == "init":
        return command_init(args)
    if args.command == "install":
        return command_install(args)
    if args.command == "remove":
        return command_remove(args)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
