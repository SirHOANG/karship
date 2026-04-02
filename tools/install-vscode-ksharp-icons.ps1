param(
    [switch]$SetAsActive,
    [string]$ExtensionsRoot = "",
    [string]$SettingsPath = "",
    [switch]$DryRun,
    [switch]$ForceResetSettings
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$sourceDir = (Resolve-Path "$PSScriptRoot\..\karship-vscode").Path
$extensionsRoot = if ([string]::IsNullOrWhiteSpace($ExtensionsRoot)) {
    Join-Path $env:USERPROFILE ".vscode\extensions"
} else {
    [System.IO.Path]::GetFullPath($ExtensionsRoot)
}
$targetDir = Join-Path $extensionsRoot "karship.karship-vscode-0.1.0"

if ($DryRun) {
    Write-Host "[DryRun] Source extension: $sourceDir"
    Write-Host "[DryRun] Target extension: $targetDir"
} else {
    if (-not (Test-Path $extensionsRoot)) {
        New-Item -ItemType Directory -Path $extensionsRoot -Force | Out-Null
    }

    if (Test-Path $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }

    Copy-Item -Path $sourceDir -Destination $targetDir -Recurse -Force
    Write-Host "Installed local VS Code extension files to: $targetDir"
}

if ($SetAsActive) {
    $settingsPath = if ([string]::IsNullOrWhiteSpace($SettingsPath)) {
        Join-Path $env:APPDATA "Code\User\settings.json"
    } else {
        [System.IO.Path]::GetFullPath($SettingsPath)
    }
    $settingsDir = Split-Path -Parent $settingsPath
    if ($DryRun) {
        Write-Host "[DryRun] Would set workbench.iconTheme in: $settingsPath"
    } else {
        if (-not (Test-Path $settingsDir)) {
            New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
        }

        $settings = @{}
        $canWriteSettings = $true
        if (Test-Path $settingsPath) {
            $raw = Get-Content -Raw -Path $settingsPath
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupPath = "$settingsPath.ksharp-backup-$stamp"
            Copy-Item -Path $settingsPath -Destination $backupPath -Force
            Write-Host "Backed up existing settings to: $backupPath"

            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                try {
                    $settings = ConvertFrom-Json -InputObject $raw -AsHashtable
                } catch {
                    if ($ForceResetSettings) {
                        Write-Warning "Could not parse existing settings.json. ForceResetSettings is on, writing minimal JSON."
                        $settings = @{}
                    } else {
                        Write-Warning "Could not parse existing settings.json. Skipping settings write to avoid data loss. Use -ForceResetSettings to override."
                        $canWriteSettings = $false
                    }
                }
            }
        }

        if ($canWriteSettings) {
            $settings["workbench.iconTheme"] = "karship-icons"
            $json = $settings | ConvertTo-Json -Depth 20
            Set-Content -Path $settingsPath -Value $json -Encoding UTF8
            Write-Host "Set workbench.iconTheme = karship-icons"
        }
    }
}

if ($DryRun) {
    Write-Host "[DryRun] Completed preview mode."
} else {
    Write-Host "Restart or reload VS Code to see the icon on .ksharp/.kpp/.k files."
}
