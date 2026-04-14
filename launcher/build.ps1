Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $scriptDir "dist"
$outputPath = Join-Path $distDir "launcher-dev.exe"
$iconPath = Join-Path (Split-Path -Parent $scriptDir) "frontend\public\512.ico"
$resourceDir = Join-Path $scriptDir "cmd\launcher"
$resourcePath = Join-Path $resourceDir "launcher.syso"
$legacyResourcePath = Join-Path $scriptDir "launcher.syso"
$targetGOOS = "windows"
$targetGOARCH = "amd64"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null

$hadGOOS = Test-Path Env:GOOS
$hadGOARCH = Test-Path Env:GOARCH
$previousGOOS = $env:GOOS
$previousGOARCH = $env:GOARCH

Push-Location $scriptDir
try {
    if (-not (Test-Path -LiteralPath $iconPath)) {
        throw "Launcher icon not found: $iconPath"
    }

    $env:GOOS = $targetGOOS
    $env:GOARCH = $targetGOARCH

    $rsrcCommand = Get-Command "rsrc.exe" -ErrorAction Stop
    New-Item -ItemType Directory -Force -Path $resourceDir | Out-Null
    & $rsrcCommand.Source -arch $targetGOARCH -ico $iconPath -o $resourcePath
    if (Test-Path -LiteralPath $legacyResourcePath) {
        Remove-Item -LiteralPath $legacyResourcePath -Force
    }

    go build -o $outputPath ./cmd/launcher
    Write-Host "Built: $outputPath"
}
finally {
    if ($hadGOOS) {
        $env:GOOS = $previousGOOS
    }
    else {
        Remove-Item Env:GOOS -ErrorAction SilentlyContinue
    }

    if ($hadGOARCH) {
        $env:GOARCH = $previousGOARCH
    }
    else {
        Remove-Item Env:GOARCH -ErrorAction SilentlyContinue
    }

    Pop-Location
}
