param(
    [switch]$AllUsers,
    [string]$InstallDir = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Add-PathEntry {
    param(
        [Parameter(Mandatory = $true)][string]$PathEntry,
        [Parameter(Mandatory = $true)][ValidateSet("User", "Machine")] [string]$Scope,
        [switch]$DryRun
    )

    $current = [Environment]::GetEnvironmentVariable("Path", $Scope)
    if ([string]::IsNullOrWhiteSpace($current)) {
        $parts = @()
    } else {
        $parts = $current.Split(";") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    }

    $normalizedEntry = [IO.Path]::GetFullPath($PathEntry).TrimEnd("\")
    $existing = $false
    foreach ($part in $parts) {
        try {
            $normalizedPart = [IO.Path]::GetFullPath($part).TrimEnd("\")
            if ($normalizedPart -ieq $normalizedEntry) {
                $existing = $true
                break
            }
        } catch {
            if ($part.TrimEnd("\") -ieq $normalizedEntry) {
                $existing = $true
                break
            }
        }
    }

    if (-not $existing) {
        $newPath = if ([string]::IsNullOrWhiteSpace($current)) {
            $PathEntry
        } else {
            "$current;$PathEntry"
        }
        if ($DryRun) {
            Write-Host "[dry-run] Would update $Scope PATH with: $PathEntry"
        } else {
            [Environment]::SetEnvironmentVariable("Path", $newPath, $Scope)
            Write-Host "Updated $Scope PATH with: $PathEntry"
        }
    } else {
        Write-Host "$Scope PATH already contains: $PathEntry"
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    if ($AllUsers) {
        $InstallDir = Join-Path $env:ProgramData "Karship\bin"
    } else {
        $InstallDir = Join-Path $env:LOCALAPPDATA "Karship\bin"
    }
}

if ($AllUsers -and -not (Test-IsAdministrator)) {
    throw "All-users install requires Administrator PowerShell. Re-run as admin with -AllUsers."
}

$scope = if ($AllUsers) { "Machine" } else { "User" }

if ($DryRun) {
    Write-Host "[dry-run] InstallDir: $InstallDir"
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$karCmdPath = Join-Path $InstallDir "kar.cmd"
$karCmdContent = @"
@echo off
setlocal
set "KARSHIP_HOME=$repoRoot"

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python -m ksharp.kar_cli %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m ksharp.kar_cli %*
  exit /b %ERRORLEVEL%
)

echo Python was not found on PATH.
exit /b 1
"@

if ($DryRun) {
    Write-Host "[dry-run] Would write launcher: $karCmdPath"
} else {
    Set-Content -Path $karCmdPath -Value $karCmdContent -Encoding Ascii
    Write-Host "Created launcher: $karCmdPath"
}

$karPs1Path = Join-Path $InstallDir "kar.ps1"
$karPs1Content = @"
`$env:KARSHIP_HOME = '$repoRoot'
python -m ksharp.kar_cli `$args
"@
if ($DryRun) {
    Write-Host "[dry-run] Would write PowerShell launcher: $karPs1Path"
} else {
    Set-Content -Path $karPs1Path -Value $karPs1Content -Encoding UTF8
    Write-Host "Created launcher: $karPs1Path"
}

Add-PathEntry -PathEntry $InstallDir -Scope $scope -DryRun:$DryRun

if (-not $DryRun) {
    if ($env:Path -notlike "*$InstallDir*") {
        $env:Path = "$InstallDir;$env:Path"
    }
    [Environment]::SetEnvironmentVariable("KARSHIP_HOME", $repoRoot, $scope)
    Write-Host "Set KARSHIP_HOME ($scope): $repoRoot"
    Write-Host ""
    Write-Host "Install complete."
    Write-Host "Open a NEW terminal, then run:"
    Write-Host "  kar --version"
    Write-Host "  kar run ksharp\hello_world.ksharp"
}
