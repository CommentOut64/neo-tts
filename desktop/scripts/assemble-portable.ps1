param(
    [string]$ReleaseRoot,
    [string]$PortableRoot,
    [string]$PortableZipPath,
    [switch]$SkipZip
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PathWithinRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $fullPath = Get-FullPath -Path $Path
    $fullRoot = Get-FullPath -Path $Root
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside root '$fullRoot': $fullPath"
    }
}

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Remove-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$AllowedRoot
    )

    Assert-PathWithinRoot -Path $Path -Root $AllowedRoot
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Content
    )

    Ensure-Directory -Path (Split-Path -Parent $Path)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Load-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$packageJsonPath = Join-Path $desktopRoot "package.json"
$portableFlavorPath = Join-Path $desktopRoot "packaging\flavors\portable.v1.json"
foreach ($requiredPath in @($packageJsonPath, $portableFlavorPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly prerequisite missing: $requiredPath"
    }
}

$packageJson = Load-JsonFile -Path $packageJsonPath
$portableFlavor = Load-JsonFile -Path $portableFlavorPath
$releaseRootBase = Join-Path $desktopRoot "release"
$releaseRootPath = if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    Join-Path $releaseRootBase ([string]$packageJson.version)
}
else {
    $ReleaseRoot
}
$releaseRootPath = Get-FullPath -Path $releaseRootPath
Assert-PathWithinRoot -Path $releaseRootPath -Root $releaseRootBase

$winUnpackedRoot = Join-Path $releaseRootPath "win-unpacked"
$exePath = Join-Path $winUnpackedRoot "NeoTTS.exe"
foreach ($requiredPath in @($winUnpackedRoot, $exePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly prerequisite missing: $requiredPath"
    }
}

$portableMarkerName = [string]$portableFlavor.portableMarker
if ([string]::IsNullOrWhiteSpace($portableMarkerName)) {
    throw "Portable flavor metadata does not declare portableMarker."
}

if ([string]::IsNullOrWhiteSpace($PortableRoot)) {
    $PortableRoot = Join-Path $releaseRootPath "NeoTTS-Portable"
}
if ([string]::IsNullOrWhiteSpace($PortableZipPath)) {
    $PortableZipPath = Join-Path $releaseRootPath ("NeoTTS-Portable-{0}.zip" -f [string]$packageJson.version)
}

$portableRootPath = Get-FullPath -Path $PortableRoot
$portableZipPathResolved = Get-FullPath -Path $PortableZipPath
Assert-PathWithinRoot -Path $portableRootPath -Root $releaseRootPath
Assert-PathWithinRoot -Path $portableZipPathResolved -Root $releaseRootPath

Write-Host "[assemble-portable] Preparing portable root..."
Remove-PathIfExists -Path $portableRootPath -AllowedRoot $releaseRootPath
if (-not $SkipZip) {
    Remove-PathIfExists -Path $portableZipPathResolved -AllowedRoot $releaseRootPath
}
Ensure-Directory -Path $portableRootPath

Get-ChildItem -LiteralPath $winUnpackedRoot -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $portableRootPath -Recurse -Force
}

$portableMarkerPath = Join-Path $portableRootPath $portableMarkerName
$portableExePath = Join-Path $portableRootPath "NeoTTS.exe"
$portableDataPath = Join-Path $portableRootPath "data"
$portableExportsPath = Join-Path $portableRootPath "exports"

Ensure-Directory -Path $portableDataPath
Ensure-Directory -Path $portableExportsPath
Write-Utf8File -Path $portableMarkerPath -Content ""

foreach ($requiredPath in @($portableExePath, $portableMarkerPath, $portableDataPath, $portableExportsPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly validation failed: missing $requiredPath"
    }
}

if ($SkipZip) {
    Write-Host "[assemble-portable] Portable root artifact completed (zip skipped):"
    Write-Host "  - root: $portableRootPath"
}
else {
    Write-Host "[assemble-portable] Creating portable zip..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $portableRootPath,
        $portableZipPathResolved,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    if (-not (Test-Path -LiteralPath $portableZipPathResolved)) {
        throw "Portable zip was not created: $portableZipPathResolved"
    }

    Write-Host "[assemble-portable] Portable artifact completed:"
    Write-Host "  - root: $portableRootPath"
    Write-Host "  - zip:  $portableZipPathResolved"
}
