param(
    [string]$BaselinePortableRoot,

    [string]$LayeredReleaseRoot,

    [string]$ReleaseId,

    [string]$OfflinePackagePath,

    [string]$WorkRoot,

    [string]$Channel = "stable",

    [int]$TimeoutSeconds = 240,

    [switch]$KeepWorkRoot
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
        throw "Missing required ${Description}: $Path"
    }
}

function Load-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
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

function Copy-DirectoryTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    if (Test-Path -LiteralPath $DestinationPath) {
        Remove-Item -LiteralPath $DestinationPath -Recurse -Force
    }
    Ensure-Directory -Path $DestinationPath
    & robocopy.exe $SourcePath $DestinationPath /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }
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

function Get-ReleaseSortKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value -notmatch '^v?(\d+)\.(\d+)\.(\d+)(?:-.+)?$') {
        throw "Release id must use v<major>.<minor>.<patch> format: $Value"
    }
    return ([int64]$Matches[1] * 1000000000000) + ([int64]$Matches[2] * 1000000) + [int64]$Matches[3]
}

function Resolve-DefaultLayeredReleaseRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DesktopRoot
    )

    $packageJson = Load-JsonFile -Path (Join-Path $DesktopRoot "package.json")
    return Join-Path (Join-Path $DesktopRoot "release") ([string]$packageJson.version)
}

function Resolve-DefaultReleaseId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LayeredRoot
    )

    $releasesRoot = Join-Path $LayeredRoot "releases"
    Assert-RequiredPath -Path $releasesRoot -Description "layered releases directory"
    $releaseDirs = @(Get-ChildItem -LiteralPath $releasesRoot -Directory | Where-Object {
        $_.Name -match '^v\d+\.\d+\.\d+$' -and (Test-Path -LiteralPath (Join-Path $_.FullName "manifest.json"))
    })
    if ($releaseDirs.Count -ne 1) {
        throw "Expected exactly one release manifest directory under $releasesRoot, found $($releaseDirs.Count). Pass -ReleaseId explicitly."
    }
    return [string]$releaseDirs[0].Name
}

function Resolve-DefaultBaselinePortableRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DesktopRoot,

        [Parameter(Mandatory = $true)]
        [string]$TargetReleaseId
    )

    $releaseRoot = Join-Path $DesktopRoot "release"
    Assert-RequiredPath -Path $releaseRoot -Description "desktop release root"
    $targetKey = Get-ReleaseSortKey -Value $TargetReleaseId
    $candidateList = New-Object System.Collections.Generic.List[object]
    foreach ($releaseDir in (Get-ChildItem -LiteralPath $releaseRoot -Directory)) {
        $portableRoots = @(Get-ChildItem -LiteralPath $releaseDir.FullName -Directory -Filter "NeoTTS-Portable*" | Where-Object {
                $_.Name -eq "NeoTTS-Portable" -or $_.Name -eq "NeoTTS-Portable-cu128" -or $_.Name -eq "NeoTTS-Portable-cu118"
            })
        foreach ($portableRoot in $portableRoots) {
            $currentPath = Join-Path $portableRoot.FullName "state\current.json"
            if (-not (Test-Path -LiteralPath $currentPath)) {
                continue
            }
            $state = Load-JsonFile -Path $currentPath
            $release = [string]$state.releaseId
            if ([string]::IsNullOrWhiteSpace($release)) {
                continue
            }
            $key = Get-ReleaseSortKey -Value $release
            if ($key -ge $targetKey) {
                continue
            }

            $runtimePriority = switch ($portableRoot.Name) {
                "NeoTTS-Portable-cu128" { 0; break }
                "NeoTTS-Portable" { 1; break }
                "NeoTTS-Portable-cu118" { 2; break }
                default { 3 }
            }
            $candidateList.Add([pscustomobject]@{
                    Path             = $portableRoot.FullName
                    ReleaseId        = $release
                    Key              = $key
                    RuntimePriority  = $runtimePriority
                    LastWriteTimeUtc = $portableRoot.LastWriteTimeUtc
                }) | Out-Null
        }
    }
    $candidates = @($candidateList | Sort-Object -Property `
        @{ Expression = "Key"; Descending = $true },
        @{ Expression = "RuntimePriority"; Ascending = $true },
        @{ Expression = "LastWriteTimeUtc"; Descending = $true })

    if ($null -eq $candidates -or $candidates.Count -eq 0) {
        throw "Could not auto-detect a baseline NeoTTS-Portable* release older than $TargetReleaseId. Pass -BaselinePortableRoot."
    }
    return [string]$candidates[0].Path
}

function Ensure-ChannelLatest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LayeredRoot,

        [Parameter(Mandatory = $true)]
        [string]$TargetReleaseId,

        [Parameter(Mandatory = $true)]
        [string]$TargetChannel
    )

    $manifestPath = Join-Path $LayeredRoot ("releases\{0}\manifest.json" -f $TargetReleaseId)
    Assert-RequiredPath -Path $manifestPath -Description "target manifest"
    $manifest = Load-JsonFile -Path $manifestPath
    if ([string]$manifest.releaseId -ne $TargetReleaseId) {
        throw "manifest.releaseId must match ReleaseId. manifest=$($manifest.releaseId), expected=$TargetReleaseId"
    }
    $manifestSha256 = Get-FileSha256 -Path $manifestPath
    $latestPath = Join-Path $LayeredRoot ("channels\{0}\latest.json" -f $TargetChannel)
    if (Test-Path -LiteralPath $latestPath) {
        $latest = Load-JsonFile -Path $latestPath
        if ([string]$latest.releaseId -eq $TargetReleaseId -and [string]$latest.manifestSha256 -eq $manifestSha256) {
            return $latestPath
        }
    }

    $latestPayload = [ordered]@{
        schemaVersion       = 1
        channel             = $TargetChannel
        enableDevRelease    = $false
        releaseId           = $TargetReleaseId
        releaseKind         = if ([string]::IsNullOrWhiteSpace([string]$manifest.releaseKind)) { "stable" } else { [string]$manifest.releaseKind }
        manifestUrl         = "releases/$TargetReleaseId/manifest.json"
        manifestSha256      = $manifestSha256
        minBootstrapVersion = "0.0.0"
        publishedAt         = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-Utf8File -Path $latestPath -Content ($latestPayload | ConvertTo-Json -Depth 20)
    return $latestPath
}

function Stop-PortableProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PortableRoot
    )

    $normalizedRoot = (Get-FullPath -Path $PortableRoot).TrimEnd('\')
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $exe = [string]$_.ExecutablePath
        -not [string]::IsNullOrWhiteSpace($exe) -and $exe.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)
    }
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Failed to stop process $($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Test-UpdatedState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PortableRoot,

        [Parameter(Mandatory = $true)]
        [string]$TargetReleaseId,

        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [Parameter(Mandatory = $true)]
        [string]$OfflineZipName
    )

    $currentPath = Join-Path $PortableRoot "state\current.json"
    if (-not (Test-Path -LiteralPath $currentPath)) {
        return $false
    }
    $current = Load-JsonFile -Path $currentPath
    if ([string]$current.releaseId -ne $TargetReleaseId) {
        return $false
    }
    if (Test-Path -LiteralPath (Join-Path $PortableRoot "state\pending-switch.json")) {
        return $false
    }
    $lastKnownGoodPath = Join-Path $PortableRoot "state\last-known-good.json"
    if (-not (Test-Path -LiteralPath $lastKnownGoodPath)) {
        return $false
    }
    $lastKnownGood = Load-JsonFile -Path $lastKnownGoodPath
    if ([string]$lastKnownGood.releaseId -ne $TargetReleaseId) {
        return $false
    }
    foreach ($packageProperty in $Manifest.packages.PSObject.Properties) {
        $packageDir = Join-Path $PortableRoot ("packages\{0}\{1}" -f $packageProperty.Name, [string]$packageProperty.Value.version)
        if (-not (Test-Path -LiteralPath $packageDir)) {
            return $false
        }
    }
    foreach ($forbiddenPath in @(
            (Join-Path $PortableRoot $OfflineZipName),
            (Join-Path $PortableRoot ("cache\offline-update\inbox\{0}" -f $OfflineZipName)),
            (Join-Path $PortableRoot ("cache\offline-update\failed\{0}" -f $OfflineZipName)),
            (Join-Path $PortableRoot ("cache\offline-update\invalid\{0}" -f $OfflineZipName))
        )) {
        if (Test-Path -LiteralPath $forbiddenPath) {
            return $false
        }
    }
    return $true
}

function Get-OfflineFailurePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PortableRoot,

        [Parameter(Mandatory = $true)]
        [string]$OfflineZipName
    )

    foreach ($relativePath in @(
            ("cache\offline-update\failed\{0}" -f $OfflineZipName),
            ("cache\offline-update\invalid\{0}" -f $OfflineZipName)
        )) {
        $path = Join-Path $PortableRoot $relativePath
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    return ""
}

function Get-DiagnosticSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PortableRoot
    )

    $paths = @(
        "state\current.json",
        "state\pending-switch.json",
        "state\last-known-good.json",
        "state\failed-release.json"
    )
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($relativePath in $paths) {
        $path = Join-Path $PortableRoot $relativePath
        if (Test-Path -LiteralPath $path) {
            $lines.Add("[$relativePath]")
            $lines.Add((Get-Content -Raw -LiteralPath $path))
        }
    }
    $launcherLogRoot = Join-Path $PortableRoot "data\logs"
    if (Test-Path -LiteralPath $launcherLogRoot) {
        $latestLog = Get-ChildItem -LiteralPath $launcherLogRoot -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -ne $latestLog) {
            $lines.Add("[latest launcher log: $($latestLog.FullName)]")
            Get-Content -LiteralPath $latestLog.FullName -Tail 80 | ForEach-Object {
                $lines.Add($_)
            }
        }
    }

    $offlineRoot = Join-Path $PortableRoot "cache\offline-update"
    if (Test-Path -LiteralPath $offlineRoot) {
        $lines.Add("[cache\offline-update]")
        Get-ChildItem -LiteralPath $offlineRoot -Recurse -File | ForEach-Object {
            $lines.Add($_.FullName)
        }
    }
    return ($lines -join [Environment]::NewLine)
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir

if ([string]::IsNullOrWhiteSpace($LayeredReleaseRoot)) {
    $LayeredReleaseRoot = Resolve-DefaultLayeredReleaseRoot -DesktopRoot $desktopRoot
}
$layeredRootPath = Get-FullPath -Path $LayeredReleaseRoot
Assert-RequiredPath -Path $layeredRootPath -Description "layered release root"

if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
    $ReleaseId = Resolve-DefaultReleaseId -LayeredRoot $layeredRootPath
}
if ($ReleaseId -notmatch '^v\d+\.\d+\.\d+$') {
    throw "ReleaseId must use v<major>.<minor>.<patch> format: $ReleaseId"
}

if ([string]::IsNullOrWhiteSpace($BaselinePortableRoot)) {
    $BaselinePortableRoot = Resolve-DefaultBaselinePortableRoot -DesktopRoot $desktopRoot -TargetReleaseId $ReleaseId
}
$baselinePortablePath = Get-FullPath -Path $BaselinePortableRoot
Assert-RequiredPath -Path $baselinePortablePath -Description "baseline portable root"
Assert-RequiredPath -Path (Join-Path $baselinePortablePath "NeoTTS.exe") -Description "baseline portable bootstrap"
Assert-RequiredPath -Path (Join-Path $baselinePortablePath "portable.flag") -Description "baseline portable flag"
Assert-RequiredPath -Path (Join-Path $baselinePortablePath "state\current.json") -Description "baseline current state"

$baselineState = Load-JsonFile -Path (Join-Path $baselinePortablePath "state\current.json")
if ([string]$baselineState.distributionKind -ne "portable") {
    throw "Baseline current.json must describe a portable distribution."
}
if ((Get-ReleaseSortKey -Value ([string]$baselineState.releaseId)) -ge (Get-ReleaseSortKey -Value $ReleaseId)) {
    throw "Baseline release $($baselineState.releaseId) must be older than target $ReleaseId."
}

$manifestPath = Join-Path $layeredRootPath ("releases\{0}\manifest.json" -f $ReleaseId)
Assert-RequiredPath -Path $manifestPath -Description "target manifest"
$manifest = Load-JsonFile -Path $manifestPath
Ensure-ChannelLatest -LayeredRoot $layeredRootPath -TargetReleaseId $ReleaseId -TargetChannel $Channel | Out-Null

if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "neo-tts-portable-offline-update-tests"
}
$workRootPath = Get-FullPath -Path $WorkRoot
Ensure-Directory -Path $workRootPath
$testRoot = Join-Path $workRootPath ("run-{0}" -f ([System.Guid]::NewGuid().ToString("N")))
$portableRoot = Join-Path $testRoot "NeoTTS-Portable"
$offlineOutputRoot = Join-Path $testRoot "offline-package"
Ensure-Directory -Path $testRoot
Ensure-Directory -Path $offlineOutputRoot

try {
    Copy-DirectoryTree -SourcePath $baselinePortablePath -DestinationPath $portableRoot

    if ([string]::IsNullOrWhiteSpace($OfflinePackagePath)) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "build-offline-update-package.ps1") `
            -LayeredReleaseRoot $layeredRootPath `
            -ReleaseId $ReleaseId `
            -Channel $Channel `
            -BaselinePortableRoot $baselinePortablePath `
            -OutputRoot $offlineOutputRoot
        if ($LASTEXITCODE -ne 0) {
            throw "build-offline-update-package.ps1 failed with exit code $LASTEXITCODE"
        }
        $OfflinePackagePath = Join-Path $offlineOutputRoot ("NeoTTS-Update-v{0}.zip" -f $ReleaseId.Substring(1))
    }

    $offlinePackageFullPath = Get-FullPath -Path $OfflinePackagePath
    Assert-RequiredPath -Path $offlinePackageFullPath -Description "offline update package"
    $offlineZipName = Split-Path -Leaf $offlinePackageFullPath
    if ($offlineZipName -ne ("NeoTTS-Update-v{0}.zip" -f $ReleaseId.Substring(1))) {
        throw "Offline package name must match target release. actual=$offlineZipName expected=NeoTTS-Update-v$($ReleaseId.Substring(1)).zip"
    }
    Copy-Item -LiteralPath $offlinePackageFullPath -Destination (Join-Path $portableRoot $offlineZipName) -Force

    Write-Host "[test-portable-offline-update] Baseline: $($baselineState.releaseId) -> Target: $ReleaseId"
    Write-Host "[test-portable-offline-update] Portable root: $portableRoot"
    Write-Host "[test-portable-offline-update] Offline package: $offlinePackageFullPath"

    $process = Start-Process -FilePath (Join-Path $portableRoot "NeoTTS.exe") -WorkingDirectory $portableRoot -PassThru
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $success = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-UpdatedState -PortableRoot $portableRoot -TargetReleaseId $ReleaseId -Manifest $manifest -OfflineZipName $offlineZipName) {
            $success = $true
            break
        }
        $offlineFailurePath = Get-OfflineFailurePath -PortableRoot $portableRoot -OfflineZipName $offlineZipName
        if (-not [string]::IsNullOrWhiteSpace($offlineFailurePath)) {
            $diagnostics = Get-DiagnosticSummary -PortableRoot $portableRoot
            throw "Portable offline update failed and moved the archive to $offlineFailurePath.`n$diagnostics"
        }
        Start-Sleep -Seconds 2
    }

    if (-not $success) {
        $diagnostics = Get-DiagnosticSummary -PortableRoot $portableRoot
        throw "Portable offline update acceptance test timed out after ${TimeoutSeconds}s.`n$diagnostics"
    }

    Stop-PortableProcesses -PortableRoot $portableRoot
    Write-Host "[test-portable-offline-update] PASS: current.json, last-known-good.json, package roots, pending switch cleanup, and offline archive cleanup all matched $ReleaseId."
    if ($KeepWorkRoot) {
        Write-Host "[test-portable-offline-update] Kept work root: $testRoot"
    }
}
catch {
    Stop-PortableProcesses -PortableRoot $portableRoot
    if ($KeepWorkRoot) {
        Write-Host "[test-portable-offline-update] Kept work root after failure: $testRoot"
    }
    throw
}
finally {
    if (-not $KeepWorkRoot) {
        Write-Host "[test-portable-offline-update] Work root: $testRoot"
    }
}
