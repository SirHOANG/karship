from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "karship.json"
LOCAL_RUNTIME_DIRNAME = ".karship"
LOCAL_SITE_PACKAGES_REL = Path(LOCAL_RUNTIME_DIRNAME) / "site-packages"


class PackageManagerError(Exception):
    pass


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
) -> dict[str, Any]:
    package_name = str(package).strip()
    if not package_name:
        raise PackageManagerError("Package name cannot be empty.")

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
) -> dict[str, Any]:
    package_name = str(package).strip()
    if not package_name:
        raise PackageManagerError("Package name cannot be empty.")

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

