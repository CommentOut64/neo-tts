param(
    [ValidateSet("default")]
    [string]$Profile = "default",

    [string]$ReleaseRoot,
    [string]$PortableRoot,
    [string]$PortableZipPath,
    [string]$RuntimeVersionOverride,
    [string]$SevenZipPath = "C:\Program Files\7-Zip\7z.exe",
    [ValidateRange(0, 9)]
    [int]$ZipCompressionLevel = 1,
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

function Resolve-SevenZipPath {
    param(
        [Parameter()]
        [AllowEmptyString()]
        [string]$ConfiguredPath
    )

    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredPath)) {
        $candidates.Add($ConfiguredPath) | Out-Null
    }
    $candidates.Add("C:\Program Files\7-Zip\7z.exe") | Out-Null

    $pathCommand = Get-Command "7z.exe" -ErrorAction SilentlyContinue
    if ($pathCommand) {
        $candidates.Add($pathCommand.Source) | Out-Null
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate) {
            return (Get-Item -LiteralPath $candidate).FullName
        }
    }

    throw "7-Zip executable not found. Install 7-Zip or pass -SevenZipPath."
}

function New-ZipArchiveWithSevenZip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDirectory,

        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,

        [Parameter(Mandatory = $true)]
        [string]$SevenZipExe,

        [ValidateRange(0, 9)]
        [int]$CompressionLevel = 1
    )

    if (-not (Test-Path -LiteralPath $SourceDirectory)) {
        throw "Zip source directory missing: $SourceDirectory"
    }

    Ensure-Directory -Path (Split-Path -Parent $ArchivePath)
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }

    Push-Location $SourceDirectory
    try {
        & $SevenZipExe "a" "-tzip" "-mx$CompressionLevel" "-mmt=on" $ArchivePath ".\*" "-r" | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $ArchivePath)) {
        throw "Zip archive was not created: $ArchivePath"
    }
}

function Get-NormalizedReleaseId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $trimmed = $Value.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        throw "ReleaseId cannot be empty."
    }
    if ($trimmed.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $trimmed
    }
    return "v$trimmed"
}

function Resolve-RootRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath,

        [Parameter(Mandatory = $true)]
        [string]$ConfiguredPath
    )

    if ([System.IO.Path]::IsPathRooted($ConfiguredPath)) {
        return Get-FullPath -Path $ConfiguredPath
    }

    $trimmed = $ConfiguredPath.Trim()
    if ($trimmed.StartsWith("./") -or $trimmed.StartsWith(".\")) {
        $trimmed = $trimmed.Substring(2)
    }

    return Join-Path $RootPath $trimmed
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Portable assembly prerequisite missing: $SourcePath"
    }

    Ensure-Directory -Path $DestinationPath
    Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
        Copy-PortableItem -SourcePath $_.FullName -DestinationPath (Join-Path $DestinationPath $_.Name)
    }
}

function Copy-PortableItem {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    $sourceItem = Get-Item -LiteralPath $SourcePath
    if ($sourceItem.PSIsContainer) {
        Ensure-Directory -Path $DestinationPath
        foreach ($entry in (Get-ChildItem -LiteralPath $SourcePath -Force)) {
            Copy-PortableItem -SourcePath $entry.FullName -DestinationPath (Join-Path $DestinationPath $entry.Name)
        }
        return
    }

    Ensure-Directory -Path (Split-Path -Parent $DestinationPath)
    if (Test-Path -LiteralPath $DestinationPath) {
        Remove-Item -LiteralPath $DestinationPath -Force
    }

    try {
        New-Item -ItemType HardLink -Path $DestinationPath -Target $SourcePath | Out-Null
    }
    catch {
        throw "Portable assembly hard link failed from '$SourcePath' to '$DestinationPath': $($_.Exception.Message)"
    }
}

function Copy-ShellPayload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,

        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot
    )

    Ensure-Directory -Path $DestinationRoot

    foreach ($entry in (Get-ChildItem -LiteralPath $SourceRoot -Force)) {
        if ($entry.Name -in @("NeoTTS.exe", "NeoTTSUpdateAgent.exe", "使用教程.txt", "manifest-lock.json")) {
            continue
        }

        if ($entry.PSIsContainer -and $entry.Name -eq "resources") {
            $resourcesDestination = Join-Path $DestinationRoot "resources"
            Ensure-Directory -Path $resourcesDestination
            foreach ($resourceEntry in (Get-ChildItem -LiteralPath $entry.FullName -Force)) {
                if ($resourceEntry.Name -eq "app-runtime") {
                    continue
                }
                Copy-PortableItem -SourcePath $resourceEntry.FullName -DestinationPath (Join-Path $resourcesDestination $resourceEntry.Name)
            }
            continue
        }

        Copy-PortableItem -SourcePath $entry.FullName -DestinationPath (Join-Path $DestinationRoot $entry.Name)
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$packageJsonPath = Join-Path $desktopRoot "package.json"
$portableFlavorPath = Join-Path $desktopRoot "packaging\flavors\portable.v1.json"
$profilePath = Join-Path $desktopRoot ("packaging\profiles\{0}.v1.json" -f $Profile)
foreach ($requiredPath in @($packageJsonPath, $portableFlavorPath, $profilePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly prerequisite missing: $requiredPath"
    }
}

$packageJson = Load-JsonFile -Path $packageJsonPath
$portableFlavor = Load-JsonFile -Path $portableFlavorPath
$profileConfig = Load-JsonFile -Path $profilePath
$releaseId = Get-NormalizedReleaseId -Value ([string]$packageJson.version)
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
$bootstrapExePath = Join-Path $winUnpackedRoot "NeoTTS.exe"
$shellExePath = Join-Path $winUnpackedRoot "NeoTTSApp.exe"
$updateAgentExePath = Join-Path $winUnpackedRoot "NeoTTSUpdateAgent.exe"
$tutorialPath = Join-Path $winUnpackedRoot "使用教程.txt"
$appRuntimeRoot = Join-Path $winUnpackedRoot "resources\app-runtime"
foreach ($requiredPath in @(
        $winUnpackedRoot,
        $bootstrapExePath,
        $shellExePath,
        $updateAgentExePath,
        (Join-Path $appRuntimeRoot "backend"),
        (Join-Path $appRuntimeRoot "frontend-dist"),
        (Join-Path $appRuntimeRoot "config"),
        (Join-Path $appRuntimeRoot "python-runtime")
    )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly prerequisite missing: $requiredPath"
    }
}

$portableMarkerName = [string]$portableFlavor.portableMarker
if ([string]::IsNullOrWhiteSpace($portableMarkerName)) {
    throw "Portable flavor metadata does not declare portableMarker."
}

$stateRootName = [string]$portableFlavor.runtimeLayout.stateRoot
$packagesRootName = [string]$portableFlavor.runtimeLayout.packagesRoot
if ([string]::IsNullOrWhiteSpace($stateRootName) -or [string]::IsNullOrWhiteSpace($packagesRootName)) {
    throw "Portable flavor metadata must declare runtimeLayout.stateRoot and runtimeLayout.packagesRoot."
}

$runtimeVersion = if ([string]::IsNullOrWhiteSpace($RuntimeVersionOverride)) {
    [string]$profileConfig.layeredPackages.pythonRuntimeVersion
}
else {
    $RuntimeVersionOverride
}
$adapterSystemVersion = [string]$profileConfig.layeredPackages.adapterSystemVersion
$supportAssetsVersion = [string]$profileConfig.layeredPackages.supportAssetsVersion
$seedModelPackagesVersion = [string]$profileConfig.layeredPackages.seedModelPackagesVersion
foreach ($requiredValue in @(
        @{ Label = "pythonRuntimeVersion"; Value = $runtimeVersion },
        @{ Label = "adapterSystemVersion"; Value = $adapterSystemVersion },
        @{ Label = "supportAssetsVersion"; Value = $supportAssetsVersion },
        @{ Label = "seedModelPackagesVersion"; Value = $seedModelPackagesVersion }
    )) {
    if ([string]::IsNullOrWhiteSpace([string]$requiredValue.Value)) {
        throw "Portable profile metadata is missing layeredPackages.$($requiredValue.Label)."
    }
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
$sevenZipExe = Resolve-SevenZipPath -ConfiguredPath $SevenZipPath

$stateRootPath = Join-Path $portableRootPath $stateRootName
$packagesRootPath = Join-Path $portableRootPath $packagesRootName
$portableMarkerPath = Join-Path $portableRootPath $portableMarkerName
$portableExePath = Join-Path $portableRootPath "NeoTTS.exe"
$portableUpdateAgentExePath = Join-Path $portableRootPath "NeoTTSUpdateAgent.exe"
$portableDataPath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.userDataRoot)
$portableConfigPath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.configRoot)
$portableTtsRegistryPath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.ttsRegistryRoot)
$portableCachePath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.cacheRoot)
$portableExportsPath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.exportsRoot)
$portableLogsPath = Resolve-RootRelativePath -RootPath $portableRootPath -ConfiguredPath ([string]$portableFlavor.userDataPolicy.logsRoot)

$bootstrapPackageRoot = Join-Path (Join-Path $packagesRootPath "bootstrap") ([string]$packageJson.version)
$updateAgentPackageRoot = Join-Path (Join-Path $packagesRootPath "update-agent") ([string]$packageJson.version)
$shellPackageRoot = Join-Path (Join-Path $packagesRootPath "shell") $releaseId
$appCorePackageRoot = Join-Path (Join-Path $packagesRootPath "app-core") $releaseId
$runtimePackageRoot = Join-Path (Join-Path $packagesRootPath "python-runtime") $runtimeVersion
$adapterSystemPackageRoot = Join-Path (Join-Path $packagesRootPath "adapter-system") $adapterSystemVersion
$supportAssetsPackageRoot = Join-Path (Join-Path $packagesRootPath "support-assets") $supportAssetsVersion
$seedModelPackagesPackageRoot = Join-Path (Join-Path $packagesRootPath "seed-model-packages") $seedModelPackagesVersion
$adapterSystemSourceRoot = Join-Path $appRuntimeRoot "adapter-system"
$supportAssetsSourceRoot = Join-Path $appRuntimeRoot "support-assets"
$seedModelPackagesSourceRoot = Join-Path $appRuntimeRoot "seed-model-packages"
$currentStatePath = Join-Path $stateRootPath "current.json"

Write-Host "[assemble-portable] Preparing portable root..."
Remove-PathIfExists -Path $portableRootPath -AllowedRoot $releaseRootPath
if (-not $SkipZip) {
    Remove-PathIfExists -Path $portableZipPathResolved -AllowedRoot $releaseRootPath
}
Ensure-Directory -Path $portableRootPath
Ensure-Directory -Path $stateRootPath
Ensure-Directory -Path $packagesRootPath
Ensure-Directory -Path $portableDataPath
Ensure-Directory -Path $portableConfigPath
Ensure-Directory -Path $portableTtsRegistryPath
Ensure-Directory -Path $portableCachePath
Ensure-Directory -Path $portableExportsPath
Ensure-Directory -Path $portableLogsPath

Write-Utf8File -Path $portableMarkerPath -Content ""
Copy-PortableItem -SourcePath $bootstrapExePath -DestinationPath $portableExePath
Copy-PortableItem -SourcePath $updateAgentExePath -DestinationPath $portableUpdateAgentExePath
if (Test-Path -LiteralPath $tutorialPath) {
    Copy-PortableItem -SourcePath $tutorialPath -DestinationPath (Join-Path $portableRootPath "使用教程.txt")
}

Ensure-Directory -Path $bootstrapPackageRoot
Ensure-Directory -Path $updateAgentPackageRoot
Copy-PortableItem -SourcePath $bootstrapExePath -DestinationPath (Join-Path $bootstrapPackageRoot "NeoTTS.exe")
Copy-PortableItem -SourcePath $updateAgentExePath -DestinationPath (Join-Path $updateAgentPackageRoot "NeoTTSUpdateAgent.exe")
Copy-ShellPayload -SourceRoot $winUnpackedRoot -DestinationRoot $shellPackageRoot
foreach ($directoryName in @("backend", "frontend-dist", "config")) {
    Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot $directoryName) -DestinationPath (Join-Path $appCorePackageRoot $directoryName)
}
Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot "python-runtime") -DestinationPath (Join-Path $runtimePackageRoot "python-runtime")
if (Test-Path -LiteralPath $adapterSystemSourceRoot) {
    Copy-DirectoryContents -SourcePath $adapterSystemSourceRoot -DestinationPath (Join-Path $adapterSystemPackageRoot "adapter-system")
}
if (Test-Path -LiteralPath $supportAssetsSourceRoot) {
    Copy-DirectoryContents -SourcePath $supportAssetsSourceRoot -DestinationPath (Join-Path $supportAssetsPackageRoot "support-assets")
}
if (Test-Path -LiteralPath $seedModelPackagesSourceRoot) {
    Copy-DirectoryContents -SourcePath $seedModelPackagesSourceRoot -DestinationPath (Join-Path $seedModelPackagesPackageRoot "seed-model-packages")
}

$currentState = [ordered]@{
    schemaVersion    = 1
    distributionKind = "portable"
    channel          = "stable"
    releaseId        = $releaseId
    packages         = [ordered]@{
        bootstrap           = [ordered]@{ version = [string]$packageJson.version }
        "update-agent"      = [ordered]@{ version = [string]$packageJson.version }
        shell               = [ordered]@{ version = $releaseId }
        "app-core"          = [ordered]@{ version = $releaseId }
        "python-runtime"    = [ordered]@{ version = $runtimeVersion }
        "adapter-system"    = [ordered]@{ version = $adapterSystemVersion }
        "support-assets"    = [ordered]@{ version = $supportAssetsVersion }
        "seed-model-packages" = [ordered]@{ version = $seedModelPackagesVersion }
    }
    paths            = [ordered]@{
        userDataRoot    = [string]$portableFlavor.userDataPolicy.userDataRoot
        configRoot      = [string]$portableFlavor.userDataPolicy.configRoot
        ttsRegistryRoot = [string]$portableFlavor.userDataPolicy.ttsRegistryRoot
        cacheRoot       = [string]$portableFlavor.userDataPolicy.cacheRoot
        exportsRoot     = [string]$portableFlavor.userDataPolicy.exportsRoot
        logsRoot        = [string]$portableFlavor.userDataPolicy.logsRoot
    }
}
Write-Utf8File -Path $currentStatePath -Content ($currentState | ConvertTo-Json -Depth 20)

foreach ($requiredPath in @(
        $portableExePath,
        $portableUpdateAgentExePath,
        $portableMarkerPath,
        $portableDataPath,
        $portableConfigPath,
        $portableTtsRegistryPath,
        $portableCachePath,
        $portableExportsPath,
        $portableLogsPath,
        $currentStatePath,
        (Join-Path $bootstrapPackageRoot "NeoTTS.exe"),
        (Join-Path $updateAgentPackageRoot "NeoTTSUpdateAgent.exe"),
        (Join-Path $shellPackageRoot "NeoTTSApp.exe"),
        (Join-Path $appCorePackageRoot "backend"),
        (Join-Path $runtimePackageRoot "python-runtime\python\python.exe")
    )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable assembly validation failed: missing $requiredPath"
    }
}

foreach ($optionalPackagePath in @(
        (Join-Path $adapterSystemPackageRoot "adapter-system\gpt-sovits"),
        (Join-Path $supportAssetsPackageRoot "support-assets\gpt-sovits"),
        (Join-Path $seedModelPackagesPackageRoot "seed-model-packages")
    )) {
    if ((Test-Path -LiteralPath (Split-Path -Parent $optionalPackagePath)) -and -not (Test-Path -LiteralPath $optionalPackagePath)) {
        throw "Portable assembly validation failed: missing $optionalPackagePath"
    }
}

if (Test-Path -LiteralPath (Join-Path $portableRootPath "NeoTTSApp.exe")) {
    throw "Portable assembly validation failed: NeoTTSApp.exe should not remain at the portable root."
}

if ($SkipZip) {
    Write-Host "[assemble-portable] Portable root artifact completed (zip skipped):"
    Write-Host "  - root:  $portableRootPath"
    Write-Host "  - state: $currentStatePath"
}
else {
    Write-Host "[assemble-portable] Creating portable zip with 7-Zip..."
    New-ZipArchiveWithSevenZip -SourceDirectory $portableRootPath `
        -ArchivePath $portableZipPathResolved `
        -SevenZipExe $sevenZipExe `
        -CompressionLevel $ZipCompressionLevel

    if (-not (Test-Path -LiteralPath $portableZipPathResolved)) {
        throw "Portable zip was not created: $portableZipPathResolved"
    }

    Write-Host "[assemble-portable] Portable artifact completed:"
    Write-Host "  - root:  $portableRootPath"
    Write-Host "  - zip:   $portableZipPathResolved"
    Write-Host "  - state: $currentStatePath"
}
