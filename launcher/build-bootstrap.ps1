Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $scriptDir "dist"
$iconPath = Join-Path (Split-Path -Parent $scriptDir) "frontend\public\512.ico"
$targetGOOS = "windows"
$targetGOARCH = "amd64"

function Build-GoBinaryWithIcon {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackagePath,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath,
        [Parameter(Mandatory = $true)]
        [string]$ResourceDir
    )

    $resourcePath = Join-Path $ResourceDir "launcher.syso"

    New-Item -ItemType Directory -Force -Path $ResourceDir | Out-Null
    & $rsrcCommand.Source -arch $targetGOARCH -ico $iconPath -o $resourcePath
    go build -ldflags "-H windowsgui" -o $OutputPath $PackagePath
    Write-Host "Built: $OutputPath"
}

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

    Build-GoBinaryWithIcon -PackagePath "./cmd/bootstrap" -OutputPath (Join-Path $distDir "NeoTTS.exe") -ResourceDir (Join-Path $scriptDir "cmd\bootstrap")
    Build-GoBinaryWithIcon -PackagePath "./cmd/update-agent" -OutputPath (Join-Path $distDir "NeoTTSUpdateAgent.exe") -ResourceDir (Join-Path $scriptDir "cmd\update-agent")
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
