param(
    [ValidateSet("default")]
    [string]$Profile = "default",

    [ValidateSet("portable", "installed")]
    [string]$Distribution = "portable",

    [string]$Channel = "stable",

    [string]$ReleaseId,

    [string]$RuntimeVersionOverride,

    [string]$StageRoot,

    [string]$ReleaseRoot,

    [string]$WinUnpackedRoot,

    [string]$BootstrapDistRoot,

    [string]$BaseUrl,

    [string]$NotesUrl,

    [string]$SevenZipPath = "C:\Program Files\7-Zip\7z.exe",

    [ValidateRange(0, 9)]
    [int]$ZipCompressionLevel = 1,

    [switch]$KeepExistingPackages,

    [switch]$SkipStageRuntime,

    [switch]$SkipBootstrapBuild,

    [switch]$SkipShellBuild,

    [switch]$SkipRuntimePackage,

    [switch]$SkipModelsPackage,

    [switch]$SkipPretrainedModelsPackage,

    [switch]$Offline
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

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$Arguments = @()
    )

    Write-Host "[build-layered-release] $Label"
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
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

function Get-ReleaseKind {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedReleaseId
    )

    if ($ResolvedReleaseId -match "-dev\d+$") {
        return "dev"
    }
    return "stable"
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Missing package source directory: $SourcePath"
    }

    Ensure-Directory -Path $DestinationPath
    Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
        Copy-LayeredWorkspaceItem -SourcePath $_.FullName -DestinationPath (Join-Path $DestinationPath $_.Name)
    }
}

function Copy-LayeredWorkspaceItem {
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
            Copy-LayeredWorkspaceItem -SourcePath $entry.FullName -DestinationPath (Join-Path $DestinationPath $entry.Name)
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
        throw "Layered release hard link failed from '$SourcePath' to '$DestinationPath': $($_.Exception.Message)"
    }
}

function Copy-ShellPayload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,

        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot "NeoTTSApp.exe"))) {
        throw "Shell package prerequisite missing: $(Join-Path $SourceRoot 'NeoTTSApp.exe')"
    }

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
                Copy-LayeredWorkspaceItem -SourcePath $resourceEntry.FullName -DestinationPath (Join-Path $resourcesDestination $resourceEntry.Name)
            }
            continue
        }

        Copy-LayeredWorkspaceItem -SourcePath $entry.FullName -DestinationPath (Join-Path $DestinationRoot $entry.Name)
    }
}

function New-PackageArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageId,

        [Parameter(Mandatory = $true)]
        [string]$Version,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Populate
    )

    $packageOutputRoot = Join-Path $packagesRoot $PackageId
    Ensure-Directory -Path $packageOutputRoot
    $archivePath = Join-Path $packageOutputRoot ("{0}.zip" -f $Version)
    if ($KeepExistingPackages -and (Test-Path -LiteralPath $archivePath)) {
        Write-Host "[build-layered-release] Reusing existing package archive: $archivePath"
    }
    else {
        $workspaceRoot = Join-Path $temporaryRoot $PackageId
        Remove-PathIfExists -Path $workspaceRoot -AllowedRoot $temporaryRoot
        Ensure-Directory -Path $workspaceRoot

        & $Populate $workspaceRoot

        if ((Get-ChildItem -LiteralPath $workspaceRoot -Force | Measure-Object).Count -eq 0) {
            throw "Package '$PackageId' produced no files."
        }

        if (Test-Path -LiteralPath $archivePath) {
            Remove-Item -LiteralPath $archivePath -Force
        }

        New-ZipArchiveWithSevenZip -SourceDirectory $workspaceRoot `
            -ArchivePath $archivePath `
            -SevenZipExe $sevenZipExe `
            -CompressionLevel $ZipCompressionLevel
    }

    if (-not (Test-Path -LiteralPath $archivePath)) {
        throw "Failed to create package archive: $archivePath"
    }

    $archiveInfo = Get-Item -LiteralPath $archivePath
    return [ordered]@{
        packageId = $PackageId
        version   = $Version
        filePath  = $archivePath
        url       = ("{0}/packages/{1}/{2}.zip" -f $baseUrlResolved.TrimEnd("/"), $PackageId, $Version)
        sha256    = Get-FileSha256 -Path $archivePath
        sizeBytes = [Int64]$archiveInfo.Length
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $desktopRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$launcherRoot = Join-Path $projectRoot "launcher"
$releaseRootBase = Join-Path $desktopRoot "release"
$stageRuntimeScript = Join-Path $scriptDir "stage-runtime.ps1"
$writeUpdateManifestScript = Join-Path $scriptDir "write-update-manifest.ps1"
$buildBootstrapScript = Join-Path $launcherRoot "build-bootstrap.ps1"
$policyPath = Join-Path $desktopRoot "packaging\update-package-policy.json"
$profilePath = Join-Path $desktopRoot ("packaging\profiles\{0}.v1.json" -f $Profile)
$packageJsonPath = Join-Path $desktopRoot "package.json"
$frontendDistPath = Join-Path $frontendRoot "dist"
$desktopDistPath = Join-Path $desktopRoot "dist"

foreach ($requiredPath in @($stageRuntimeScript, $writeUpdateManifestScript, $buildBootstrapScript, $policyPath, $profilePath, $packageJsonPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Layered release prerequisite missing: $requiredPath"
    }
}

$desktopPackage = Load-JsonFile -Path $packageJsonPath
$profileConfig = Load-JsonFile -Path $profilePath
$policyConfig = Load-JsonFile -Path $policyPath
$packageVersion = [string]$desktopPackage.version
if ([string]::IsNullOrWhiteSpace($packageVersion)) {
    throw "desktop/package.json version is required."
}

if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
    $ReleaseId = $packageVersion
}
$releaseIdResolved = Get-NormalizedReleaseId -Value $ReleaseId
$releaseKind = Get-ReleaseKind -ResolvedReleaseId $releaseIdResolved

if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $releaseRootBase $packageVersion
}
if ([string]::IsNullOrWhiteSpace($StageRoot)) {
    $StageRoot = Join-Path $desktopRoot ".stage"
}
if ([string]::IsNullOrWhiteSpace($WinUnpackedRoot)) {
    $WinUnpackedRoot = Join-Path $ReleaseRoot "win-unpacked"
}
if ([string]::IsNullOrWhiteSpace($BootstrapDistRoot)) {
    $BootstrapDistRoot = Join-Path $launcherRoot "dist"
}

$releaseRootPath = Get-FullPath -Path $ReleaseRoot
$stageRootPath = Get-FullPath -Path $StageRoot
$winUnpackedRootPath = Get-FullPath -Path $WinUnpackedRoot
$bootstrapDistRootPath = Get-FullPath -Path $BootstrapDistRoot
Assert-PathWithinRoot -Path $releaseRootPath -Root $releaseRootBase
Assert-PathWithinRoot -Path $stageRootPath -Root $desktopRoot
Assert-PathWithinRoot -Path $winUnpackedRootPath -Root $releaseRootPath
Assert-PathWithinRoot -Path $bootstrapDistRootPath -Root $launcherRoot

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = [string]$policyConfig.baseUrl
}
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "https://cdn.example.com/neotts"
}
$baseUrlResolved = $BaseUrl.TrimEnd("/")

if ([string]::IsNullOrWhiteSpace($NotesUrl)) {
    $notesUrlTemplate = [string]$policyConfig.notesUrlTemplate
    if ([string]::IsNullOrWhiteSpace($notesUrlTemplate)) {
        $NotesUrl = "$baseUrlResolved/release-notes/$releaseIdResolved.md"
    }
    else {
        $NotesUrl = $notesUrlTemplate.Replace("{releaseId}", $releaseIdResolved)
    }
}

$includePackagesConfig = $policyConfig.includePackages
$includeRuntimePackage = [bool]($includePackagesConfig.'python-runtime')
$includeAdapterSystemPackage = [bool]($includePackagesConfig.'adapter-system')
$includeSupportAssetsPackage = [bool]($includePackagesConfig.'support-assets')
$includeSeedModelPackagesPackage = [bool]($includePackagesConfig.'seed-model-packages')
if ($SkipRuntimePackage) {
    $includeRuntimePackage = $false
}
if ($SkipModelsPackage) {
    $includeSupportAssetsPackage = $false
}
if ($SkipPretrainedModelsPackage) {
    $includeSeedModelPackagesPackage = $false
}

if (-not $SkipStageRuntime) {
    $stageRuntimeArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $stageRuntimeScript,
        "-Profile", $Profile,
        "-Flavor", $Distribution,
        "-StageRoot", $stageRootPath
    )
    if ($Offline) {
        $stageRuntimeArgs += "-Offline"
    }
    Invoke-NativeStep -Label "Stage runtime for layered release" `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments $stageRuntimeArgs
}

if (-not $SkipBootstrapBuild) {
    Invoke-NativeStep -Label "Build bootstrap executables" `
        -WorkingDirectory $projectRoot `
        -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $buildBootstrapScript
        )
}

if (-not $SkipShellBuild) {
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDistPath "index.html"))) {
        Invoke-NativeStep -Label "Build frontend for layered release" `
            -WorkingDirectory $frontendRoot `
            -FilePath "npm.cmd" `
            -Arguments @("run", "build")
    }
    if (-not (Test-Path -LiteralPath $desktopDistPath)) {
        Invoke-NativeStep -Label "Build desktop TypeScript for layered release" `
            -WorkingDirectory $desktopRoot `
            -FilePath "npm.cmd" `
            -Arguments @("run", "build")
    }
    Invoke-NativeStep -Label "Build Windows dir artifact for layered release" `
        -WorkingDirectory $desktopRoot `
        -FilePath "npm.cmd" `
        -Arguments @("run", "package:builder")
}

$launcherBootstrapExe = Join-Path $bootstrapDistRootPath "NeoTTS.exe"
$launcherUpdateAgentExe = Join-Path $bootstrapDistRootPath "NeoTTSUpdateAgent.exe"
$shellExe = Join-Path $winUnpackedRootPath "NeoTTSApp.exe"
$appRuntimeRoot = Join-Path $stageRootPath "app-runtime"
$appCoreRoot = $appRuntimeRoot
$runtimeRoot = Join-Path $appRuntimeRoot "python-runtime"
$adapterSystemRoot = Join-Path $appRuntimeRoot "adapter-system"
$supportAssetsRoot = Join-Path $appRuntimeRoot "support-assets"
$seedModelPackagesRoot = Join-Path $appRuntimeRoot "seed-model-packages"
$manifestPath = Join-Path (Join-Path (Join-Path $releaseRootPath "releases") $releaseIdResolved) "manifest.json"
$packagesRoot = Join-Path $releaseRootPath "packages"
$temporaryRoot = Join-Path $releaseRootPath ".layered-temp"

foreach ($requiredPath in @(
        $launcherBootstrapExe,
        $launcherUpdateAgentExe,
        $shellExe,
        (Join-Path $appCoreRoot "backend"),
        (Join-Path $appCoreRoot "frontend-dist"),
        (Join-Path $appCoreRoot "config")
    )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Layered release prerequisite missing: $requiredPath"
    }
}
if ($includeRuntimePackage -and -not (Test-Path -LiteralPath $runtimeRoot)) {
    throw "Layered release prerequisite missing: $runtimeRoot"
}
if ($includeAdapterSystemPackage -and -not (Test-Path -LiteralPath $adapterSystemRoot)) {
    throw "Layered release prerequisite missing: $adapterSystemRoot"
}
if ($includeSupportAssetsPackage -and -not (Test-Path -LiteralPath $supportAssetsRoot)) {
    throw "Layered release prerequisite missing: $supportAssetsRoot"
}
if ($includeSeedModelPackagesPackage -and -not (Test-Path -LiteralPath $seedModelPackagesRoot)) {
    throw "Layered release prerequisite missing: $seedModelPackagesRoot"
}

$sevenZipExe = Resolve-SevenZipPath -ConfiguredPath $SevenZipPath
Ensure-Directory -Path $releaseRootPath
if (-not $KeepExistingPackages) {
    Remove-PathIfExists -Path $packagesRoot -AllowedRoot $releaseRootPath
}
Remove-PathIfExists -Path (Split-Path -Parent $manifestPath) -AllowedRoot $releaseRootPath
Remove-PathIfExists -Path $temporaryRoot -AllowedRoot $releaseRootPath
Ensure-Directory -Path $packagesRoot
Ensure-Directory -Path $temporaryRoot

$runtimeVersion = if ([string]::IsNullOrWhiteSpace($RuntimeVersionOverride)) {
    [string]$profileConfig.layeredPackages.pythonRuntimeVersion
}
else {
    $RuntimeVersionOverride
}
$adapterSystemVersion = [string]$profileConfig.layeredPackages.adapterSystemVersion
$supportAssetsVersion = [string]$profileConfig.layeredPackages.supportAssetsVersion
$seedModelPackagesVersion = [string]$profileConfig.layeredPackages.seedModelPackagesVersion
if ($includeRuntimePackage -and [string]::IsNullOrWhiteSpace($runtimeVersion)) {
    throw "Profile '$Profile' must declare layeredPackages.pythonRuntimeVersion."
}
if ($includeAdapterSystemPackage -and [string]::IsNullOrWhiteSpace($adapterSystemVersion)) {
    throw "Profile '$Profile' must declare layeredPackages.adapterSystemVersion."
}
if ($includeSupportAssetsPackage -and [string]::IsNullOrWhiteSpace($supportAssetsVersion)) {
    throw "Profile '$Profile' must declare layeredPackages.supportAssetsVersion."
}
if ($includeSeedModelPackagesPackage -and [string]::IsNullOrWhiteSpace($seedModelPackagesVersion)) {
    throw "Profile '$Profile' must declare layeredPackages.seedModelPackagesVersion."
}

$packageEntries = New-Object System.Collections.Generic.List[object]
try {
    $packageEntries.Add((New-PackageArchive -PackageId "bootstrap" -Version $packageVersion -Populate {
                param($workspaceRoot)
                Copy-LayeredWorkspaceItem -SourcePath $launcherBootstrapExe -DestinationPath (Join-Path $workspaceRoot "NeoTTS.exe")
            })) | Out-Null
    $packageEntries.Add((New-PackageArchive -PackageId "update-agent" -Version $packageVersion -Populate {
                param($workspaceRoot)
                Copy-LayeredWorkspaceItem -SourcePath $launcherUpdateAgentExe -DestinationPath (Join-Path $workspaceRoot "NeoTTSUpdateAgent.exe")
            })) | Out-Null
    $packageEntries.Add((New-PackageArchive -PackageId "shell" -Version $releaseIdResolved -Populate {
                param($workspaceRoot)
                Copy-ShellPayload -SourceRoot $winUnpackedRootPath -DestinationRoot $workspaceRoot
            })) | Out-Null
    $packageEntries.Add((New-PackageArchive -PackageId "app-core" -Version $releaseIdResolved -Populate {
                param($workspaceRoot)
                foreach ($directoryName in @("backend", "frontend-dist", "config")) {
                    $sourcePath = Join-Path $appCoreRoot $directoryName
                    Copy-DirectoryContents -SourcePath $sourcePath -DestinationPath (Join-Path $workspaceRoot $directoryName)
                }
            })) | Out-Null

    if ($includeRuntimePackage) {
        $packageEntries.Add((New-PackageArchive -PackageId "python-runtime" -Version $runtimeVersion -Populate {
                    param($workspaceRoot)
                    Copy-DirectoryContents -SourcePath $runtimeRoot -DestinationPath (Join-Path $workspaceRoot "python-runtime")
                })) | Out-Null
    }
    if ($includeAdapterSystemPackage) {
        $packageEntries.Add((New-PackageArchive -PackageId "adapter-system" -Version $adapterSystemVersion -Populate {
                    param($workspaceRoot)
                    Copy-DirectoryContents -SourcePath $adapterSystemRoot -DestinationPath (Join-Path $workspaceRoot "adapter-system")
                })) | Out-Null
    }
    if ($includeSupportAssetsPackage) {
        $packageEntries.Add((New-PackageArchive -PackageId "support-assets" -Version $supportAssetsVersion -Populate {
                    param($workspaceRoot)
                    Copy-DirectoryContents -SourcePath $supportAssetsRoot -DestinationPath (Join-Path $workspaceRoot "support-assets")
                })) | Out-Null
    }
    if ($includeSeedModelPackagesPackage) {
        $packageEntries.Add((New-PackageArchive -PackageId "seed-model-packages" -Version $seedModelPackagesVersion -Populate {
                    param($workspaceRoot)
                    Copy-DirectoryContents -SourcePath $seedModelPackagesRoot -DestinationPath (Join-Path $workspaceRoot "seed-model-packages")
                })) | Out-Null
    }

    $packagesJson = $packageEntries | ConvertTo-Json -Depth 20
    $packagesPayloadPath = Join-Path $temporaryRoot "packages.json"
    Write-Utf8File -Path $packagesPayloadPath -Content $packagesJson
    Invoke-NativeStep -Label "Write layered release manifest" `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $writeUpdateManifestScript,
            "-ManifestPath", $manifestPath,
            "-ReleaseId", $releaseIdResolved,
            "-Channel", $Channel,
            "-ReleaseKind", $releaseKind,
            "-NotesUrl", $NotesUrl,
            "-PackagesPath", $packagesPayloadPath
        )
}
finally {
    Remove-PathIfExists -Path $temporaryRoot -AllowedRoot $releaseRootPath
}

Write-Host "[build-layered-release] Layered release artifacts completed:"
foreach ($packageEntry in $packageEntries) {
    Write-Host ("  - {0}: {1}" -f [string]$packageEntry.packageId, [string]$packageEntry.filePath)
}
Write-Host "  - manifest: $manifestPath"
