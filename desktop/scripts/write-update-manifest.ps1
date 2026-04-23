param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,

    [Parameter(Mandatory = $true)]
    [string]$ReleaseId,

    [string]$Channel = "stable",

    [string]$ReleaseKind = "stable",

    [string]$NotesUrl,

    [string]$PackagesJson,

    [string]$PackagesPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    Ensure-Directory -Path (Split-Path -Parent $Path)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

if ([string]::IsNullOrWhiteSpace($PackagesJson) -and [string]::IsNullOrWhiteSpace($PackagesPath)) {
    throw "PackagesJson or PackagesPath is required."
}

$packagesPayload = if (-not [string]::IsNullOrWhiteSpace($PackagesPath)) {
    Get-Content -Raw -LiteralPath $PackagesPath
}
else {
    $PackagesJson
}

$parsedPackages = $packagesPayload | ConvertFrom-Json
$packages = if ($parsedPackages -is [System.Array]) {
    $parsedPackages
}
else {
    @($parsedPackages)
}
if ($packages.Count -eq 0) {
    throw "PackagesJson must contain at least one package entry."
}

$packageMap = [ordered]@{}
foreach ($package in $packages) {
    $packageId = [string]$package.packageId
    if ([string]::IsNullOrWhiteSpace($packageId)) {
        throw "Package entry is missing packageId."
    }

    $sizeBytes = if ($null -eq $package.sizeBytes -or [string]::IsNullOrWhiteSpace([string]$package.sizeBytes)) {
        0
    }
    else {
        [Int64]$package.sizeBytes
    }

    $packageMap[$packageId] = [ordered]@{
        version   = [string]$package.version
        url       = [string]$package.url
        sha256    = [string]$package.sha256
        sizeBytes = $sizeBytes
    }
}

$manifest = [ordered]@{
    schemaVersion = 1
    releaseId     = $ReleaseId
    channel       = $Channel
    releaseKind   = $ReleaseKind
    notesUrl      = $NotesUrl
    packages      = $packageMap
}

Write-Utf8File -Path $ManifestPath -Content ($manifest | ConvertTo-Json -Depth 20)
Write-Host "[write-update-manifest] Wrote manifest: $ManifestPath"
