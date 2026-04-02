param(
    [string]$KSharpPngPath = "$PSScriptRoot\..\ksharp\assets\ksharp.png",
    [string]$KppPngPath = "$PSScriptRoot\..\ksharp\assets\kpp.png",
    [string]$KPngPath = "$PSScriptRoot\..\ksharp\assets\k.png",
    [string]$KSharpIcoPath = "$PSScriptRoot\..\ksharp\assets\ksharp.ico",
    [string]$KppIcoPath = "$PSScriptRoot\..\ksharp\assets\kpp.ico",
    [string]$KIcoPath = "$PSScriptRoot\..\ksharp\assets\k.ico",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Convert-PngToIco {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePngPath,
        [Parameter(Mandatory = $true)][string]$TargetIcoPath
    )

    Add-Type -AssemblyName System.Drawing

    $image = [System.Drawing.Image]::FromFile($SourcePngPath)
    try {
        $size = 256
        $bitmap = New-Object System.Drawing.Bitmap($size, $size)
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.Clear([System.Drawing.Color]::Transparent)
                $graphics.DrawImage($image, 0, 0, $size, $size)
            } finally {
                $graphics.Dispose()
            }

            $pngStream = New-Object System.IO.MemoryStream
            try {
                $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
                $pngBytes = $pngStream.ToArray()
            } finally {
                $pngStream.Dispose()
            }
        } finally {
            $bitmap.Dispose()
        }
    } finally {
        $image.Dispose()
    }

    $targetDir = Split-Path -Parent $TargetIcoPath
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $fileStream = [System.IO.File]::Open($TargetIcoPath, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter($fileStream)
    try {
        $writer.Write([UInt16]0) # reserved
        $writer.Write([UInt16]1) # type: icon
        $writer.Write([UInt16]1) # image count
        $writer.Write([Byte]0)   # width 256
        $writer.Write([Byte]0)   # height 256
        $writer.Write([Byte]0)   # palette
        $writer.Write([Byte]0)   # reserved
        $writer.Write([UInt16]1) # planes
        $writer.Write([UInt16]32)# bpp
        $writer.Write([UInt32]$pngBytes.Length)
        $writer.Write([UInt32]22)# data offset
        $writer.Write($pngBytes)
    } finally {
        $writer.Close()
        $fileStream.Close()
    }
}

function Set-RegDefault {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Value
    )
    New-Item -Path $Path -Force | Out-Null
    New-ItemProperty -Path $Path -Name "(default)" -Value $Value -PropertyType String -Force | Out-Null
}

$configs = @(
    [PSCustomObject]@{
        Extension = ".ksharp"
        ProgId = "Karship.KSharpFile"
        Description = "Karship K# Source File"
        Png = [System.IO.Path]::GetFullPath((Resolve-Path $KSharpPngPath).Path)
        Ico = [System.IO.Path]::GetFullPath($KSharpIcoPath)
    },
    [PSCustomObject]@{
        Extension = ".kpp"
        ProgId = "Karship.KPPFile"
        Description = "Karship K++ Source File"
        Png = [System.IO.Path]::GetFullPath((Resolve-Path $KppPngPath).Path)
        Ico = [System.IO.Path]::GetFullPath($KppIcoPath)
    },
    [PSCustomObject]@{
        Extension = ".k"
        ProgId = "Karship.KFile"
        Description = "Karship K Source File"
        Png = [System.IO.Path]::GetFullPath((Resolve-Path $KPngPath).Path)
        Ico = [System.IO.Path]::GetFullPath($KIcoPath)
    }
)

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
$openCommand = if ($null -ne $pythonCmd) {
    "`"$($pythonCmd.Source)`" -m ksharp `"%1`""
} else {
    "`"%SystemRoot%\System32\notepad.exe`" `"%1`""
}

if ($DryRun) {
    foreach ($config in $configs) {
        Write-Host "[DryRun] $($config.Extension) => $($config.Png) -> $($config.Ico) (ProgId: $($config.ProgId))"
    }
    Write-Host "[DryRun] Would set open command: $openCommand"
    exit 0
}

foreach ($config in $configs) {
    if (-not (Test-Path $config.Png)) {
        throw "PNG icon not found for $($config.Extension): $($config.Png)"
    }

    Convert-PngToIco -SourcePngPath $config.Png -TargetIcoPath $config.Ico
    Write-Host "Created ICO: $($config.Ico)"
}

$classesRoot = "HKCU:\Software\Classes"

foreach ($config in $configs) {
    Set-RegDefault -Path "$classesRoot\$($config.ProgId)" -Value $config.Description
    Set-RegDefault -Path "$classesRoot\$($config.ProgId)\DefaultIcon" -Value $config.Ico
    Set-RegDefault -Path "$classesRoot\$($config.ProgId)\shell\open\command" -Value $openCommand
    Set-RegDefault -Path "$classesRoot\$($config.Extension)" -Value $config.ProgId
}

$ie4uinit = Join-Path $env:SystemRoot "System32\ie4uinit.exe"
if (Test-Path $ie4uinit) {
    Start-Process -FilePath $ie4uinit -ArgumentList "-show" -NoNewWindow -Wait
}

Write-Host "Karship file icon registration complete:"
foreach ($config in $configs) {
    Write-Host "  $($config.Extension) -> $($config.ProgId)"
}
