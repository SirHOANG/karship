param(
    [switch]$SetAsActive,
    [string]$ExtensionsRoot = "",
    [string]$SettingsPath = "",
    [switch]$DryRun,
    [switch]$ForceResetSettings
)

& "$PSScriptRoot\install-vscode-ksharp-icons.ps1" `
    -SetAsActive:$SetAsActive `
    -ExtensionsRoot $ExtensionsRoot `
    -SettingsPath $SettingsPath `
    -DryRun:$DryRun `
    -ForceResetSettings:$ForceResetSettings
