Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $scriptDir "dist"
$outputPath = Join-Path $distDir "launcher.exe"
$iconPath = Join-Path (Split-Path -Parent $scriptDir) "frontend\public\512.ico"
$resourceDir = Join-Path $scriptDir "cmd\launcher"
$resourcePath = Join-Path $resourceDir "launcher.syso"
$legacyResourcePath = Join-Path $scriptDir "launcher.syso"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null

Push-Location $scriptDir
try {
    if (-not (Test-Path -LiteralPath $iconPath)) {
        throw "Launcher icon not found: $iconPath"
    }

    $rsrcCommand = Get-Command "rsrc.exe" -ErrorAction Stop
    New-Item -ItemType Directory -Force -Path $resourceDir | Out-Null
    & $rsrcCommand.Source -ico $iconPath -o $resourcePath
    if (Test-Path -LiteralPath $legacyResourcePath) {
        Remove-Item -LiteralPath $legacyResourcePath -Force
    }

    go build -o $outputPath ./cmd/launcher
    Write-Host "Built: $outputPath"
}
finally {
    Pop-Location
}
