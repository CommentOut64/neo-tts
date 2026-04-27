param(
    [Parameter(Mandatory = $true)]
    [string]$LayeredReleaseRoot,

    [Parameter(Mandatory = $true)]
    [string]$ReleaseId,

    [ValidateSet("portable")]
    [string]$Distribution = "portable",

    [string]$Channel = "stable",

    [string]$OutputRoot,

    [string]$BaselinePortableRoot,

    [string]$BaselineCurrentJson,

    [string[]]$IncludePackages,

    [switch]$Full
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

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Assert-RequiredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing required offline update ${Description}: $Path"
    }
}

function Load-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    Ensure-Directory -Path (Split-Path -Parent $Path)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
            return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $sha256.Dispose()
    }
}

function Copy-ReleaseObject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$TargetRoot,

        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $targetPath = Join-Path $TargetRoot $RelativePath
    Ensure-Directory -Path (Split-Path -Parent $targetPath)
    Copy-Item -LiteralPath $SourcePath -Destination $targetPath -Force
}

function Resolve-BaselineCurrentPath {
    param(
        [string]$PortableRoot,
        [string]$CurrentJson
    )

    if (-not [string]::IsNullOrWhiteSpace($CurrentJson)) {
        return Get-FullPath -Path $CurrentJson
    }
    if (-not [string]::IsNullOrWhiteSpace($PortableRoot)) {
        return Get-FullPath -Path (Join-Path $PortableRoot "state\current.json")
    }
    return ""
}

function Test-PackageSelected {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageId,

        [string[]]$AllowedPackages
    )

    if ($null -eq $AllowedPackages -or $AllowedPackages.Count -eq 0) {
        return $true
    }
    foreach ($allowed in $AllowedPackages) {
        if ([string]::Equals($PackageId, $allowed, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

if ($ReleaseId -notmatch '^v\d+\.\d+\.\d+$') {
    throw "ReleaseId must use v<major>.<minor>.<patch> format: $ReleaseId"
}

$layeredRootPath = Get-FullPath -Path $LayeredReleaseRoot
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = $layeredRootPath
}
$outputRootPath = Get-FullPath -Path $OutputRoot

Assert-RequiredPath -Path $layeredRootPath -Description "layered release root"

$latestPath = Join-Path $layeredRootPath ("channels\{0}\latest.json" -f $Channel)
$manifestPath = Join-Path $layeredRootPath ("releases\{0}\manifest.json" -f $ReleaseId)
$packagesPath = Join-Path $layeredRootPath "packages"

Assert-RequiredPath -Path $manifestPath -Description "manifest.json"
Assert-RequiredPath -Path $packagesPath -Description "packages directory"

$manifest = Load-JsonFile -Path $manifestPath
if ($manifest.releaseId -ne $ReleaseId) {
    throw "manifest.releaseId must match ReleaseId. manifest=$($manifest.releaseId), expected=$ReleaseId"
}
$manifestSha256 = Get-FileSha256 -Path $manifestPath
$latestPayload = [ordered]@{
    schemaVersion       = 1
    channel             = $Channel
    enableDevRelease    = $false
    releaseId           = $ReleaseId
    releaseKind         = if ([string]::IsNullOrWhiteSpace([string]$manifest.releaseKind)) { "stable" } else { [string]$manifest.releaseKind }
    manifestUrl         = "releases/$ReleaseId/manifest.json"
    manifestSha256      = $manifestSha256
    minBootstrapVersion = "0.0.0"
    publishedAt         = (Get-Date).ToUniversalTime().ToString("o")
}
Write-Utf8NoBomFile -Path $latestPath -Content ($latestPayload | ConvertTo-Json -Depth 20)
$latest = Load-JsonFile -Path $latestPath
if ($latest.releaseId -ne $ReleaseId) {
    throw "latest.releaseId must match ReleaseId. latest=$($latest.releaseId), expected=$ReleaseId"
}
if ([string]::IsNullOrWhiteSpace($latest.manifestSha256)) {
    throw "latest.manifestSha256 is required"
}
if ($latest.manifestSha256.ToLowerInvariant() -ne $manifestSha256) {
    throw "latest.manifestSha256 does not match manifest.json. latest=$($latest.manifestSha256), actual=$manifestSha256"
}

$baselineCurrentPath = Resolve-BaselineCurrentPath -PortableRoot $BaselinePortableRoot -CurrentJson $BaselineCurrentJson
$baselinePackages = $null
if (-not [string]::IsNullOrWhiteSpace($baselineCurrentPath)) {
    Assert-RequiredPath -Path $baselineCurrentPath -Description "baseline current.json"
    $baselineState = Load-JsonFile -Path $baselineCurrentPath
    if ($null -ne $baselineState.packages) {
        $baselinePackages = $baselineState.packages
    }
}

Ensure-Directory -Path $outputRootPath

$zipName = "NeoTTS-Update-v$($ReleaseId.Substring(1)).zip"
$zipPath = Join-Path $outputRootPath $zipName
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

$tempRoot = Join-Path $outputRootPath (".offline-update-{0}" -f ([System.Guid]::NewGuid().ToString("N")))
try {
    Ensure-Directory -Path $tempRoot
    Copy-ReleaseObject -SourcePath $latestPath -TargetRoot $tempRoot -RelativePath ("channels\{0}\latest.json" -f $Channel)
    Copy-ReleaseObject -SourcePath $manifestPath -TargetRoot $tempRoot -RelativePath ("releases\{0}\manifest.json" -f $ReleaseId)

    $copiedPackageCount = 0
    foreach ($packageProperty in $manifest.packages.PSObject.Properties) {
        $packageId = $packageProperty.Name
        $packageVersion = $packageProperty.Value.version
        if ([string]::IsNullOrWhiteSpace($packageId) -or [string]::IsNullOrWhiteSpace($packageVersion)) {
            throw "manifest package entry is missing package id or version"
        }
        if ($packageId -match '[\\/]' -or $packageVersion -match '[\\/]') {
            throw "manifest package entry contains invalid path separator: $packageId $packageVersion"
        }
        if (-not (Test-PackageSelected -PackageId $packageId -AllowedPackages $IncludePackages)) {
            continue
        }
        if (-not $Full -and $null -ne $baselinePackages) {
            $baselinePackage = $baselinePackages.PSObject.Properties[$packageId]
            if ($null -ne $baselinePackage -and [string]$baselinePackage.Value.version -eq [string]$packageVersion) {
                continue
            }
        }
        $packageArchivePath = Join-Path $packagesPath (Join-Path $packageId ("{0}.zip" -f $packageVersion))
        Assert-RequiredPath -Path $packageArchivePath -Description "package archive $packageId/$packageVersion"
        Copy-ReleaseObject -SourcePath $packageArchivePath -TargetRoot $tempRoot -RelativePath ("packages\{0}\{1}.zip" -f $packageId, $packageVersion)
        $copiedPackageCount++
    }
    if ($copiedPackageCount -eq 0) {
        throw "No package archives selected for offline update package."
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open(
        $zipPath,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        $tempRootPrefix = $tempRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        Get-ChildItem -LiteralPath $tempRoot -Recurse -File | ForEach-Object {
            $fullName = [System.IO.Path]::GetFullPath($_.FullName)
            $relativePath = $fullName.Substring($tempRootPrefix.Length).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $_.FullName,
                $relativePath,
                $(if ([System.IO.Path]::GetExtension($_.FullName).Equals(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
                    [System.IO.Compression.CompressionLevel]::NoCompression
                }
                else {
                    [System.IO.Compression.CompressionLevel]::Optimal
                })
            ) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

Write-Host "[build-offline-update-package] Created $zipPath for $Distribution release $ReleaseId."
