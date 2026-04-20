param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    & $Python -m PyInstaller --clean --noconfirm kar.spec
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
