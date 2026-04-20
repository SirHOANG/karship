#!/usr/bin/env bash
set -euo pipefail

python_bin="${1:-python3}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_root"
"$python_bin" -m PyInstaller --clean --noconfirm kar.spec
