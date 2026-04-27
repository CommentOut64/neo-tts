param(
    [ValidateSet("default")]
    [string]$Profile = "default",

    [ValidateSet("portable", "installed")]
    [string]$Distribution = "portable",

    [ValidateSet("cu128", "cu118")]
    [string]$CudaRuntime = "cu128",

    [switch]$BuildCudaRuntimeVariants,

    [switch]$SkipPortableZip,

    [switch]$BuildUpdatePackages,

    [switch]$SkipPackagedPythonCompile,

    [string]$InnoSetupCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",

    [string]$SevenZipPath = "C:\Program Files\7-Zip\7z.exe",

    [ValidateRange(0, 9)]
    [int]$ZipCompressionLevel = 1,

    [switch]$KeepWinUnpacked,

    [switch]$SkipReleaseClean,

    [switch]$Offline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:StepTimings = New-Object System.Collections.Generic.List[object]

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

function Remove-DirectoryIfExists {
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

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
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

function Get-TextSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hashBytes = $sha256.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-RelativePathNormalized {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,

        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $fullBasePath = Get-FullPath -Path $BasePath
    $fullTargetPath = Get-FullPath -Path $TargetPath
    if (-not $fullBasePath.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $fullBasePath = "$fullBasePath$([System.IO.Path]::DirectorySeparatorChar)"
    }
    $baseUri = New-Object System.Uri($fullBasePath)
    $targetUri = New-Object System.Uri($fullTargetPath)
    return ([System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString())).Replace("\", "/")
}

function Get-FilteredFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        return @()
    }

    $item = Get-Item -LiteralPath $SourcePath
    if (-not $item.PSIsContainer) {
        return @($item)
    }

    return Get-ChildItem -LiteralPath $SourcePath -Recurse -File
}

function Get-PathFingerprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return "missing"
    }

    $item = Get-Item -LiteralPath $Path
    if (-not $item.PSIsContainer) {
        return Get-TextSha256 -Text ("file|{0}|{1}|{2}" -f $item.Name, $item.Length, $item.LastWriteTimeUtc.Ticks)
    }

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($file in (Get-FilteredFiles -SourcePath $Path | Sort-Object FullName)) {
        $relativePath = Get-RelativePathNormalized -BasePath $Path -TargetPath $file.FullName
        $lines.Add(("{0}|{1}|{2}" -f $relativePath, $file.Length, $file.LastWriteTimeUtc.Ticks)) | Out-Null
    }
    return Get-TextSha256 -Text (($lines -join "`n"))
}

function Get-FingerprintFromPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath,

        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($path in $Paths) {
        $label = if (Test-Path -LiteralPath $path) {
            Get-RelativePathNormalized -BasePath $RootPath -TargetPath $path
        }
        else {
            $path
        }
        $lines.Add(("{0}|{1}" -f $label, (Get-PathFingerprint -Path $path))) | Out-Null
    }
    return Get-TextSha256 -Text (($lines -join "`n"))
}

function Get-BuildMetadataPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$StepName
    )

    return Join-Path $MetadataRoot ("{0}.json" -f $StepName)
}

function Test-BuildStepReusable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$StepName,

        [Parameter(Mandatory = $true)]
        [string]$InputFingerprint,

        [Parameter(Mandatory = $true)]
        [string[]]$RequiredPaths
    )

    $metadataPath = Get-BuildMetadataPath -MetadataRoot $MetadataRoot -StepName $StepName
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        return $false
    }

    $metadata = Load-JsonFile -Path $metadataPath
    if ([string]$metadata.inputFingerprint -ne $InputFingerprint) {
        return $false
    }

    foreach ($requiredPath in $RequiredPaths) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            return $false
        }
    }

    return $true
}

function Write-BuildStepMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$StepName,

        [Parameter(Mandatory = $true)]
        [string]$InputFingerprint,

        [Parameter(Mandatory = $true)]
        [string[]]$OutputPaths
    )

    Ensure-Directory -Path $MetadataRoot
    $metadata = [ordered]@{
        schemaVersion    = 1
        step             = $StepName
        inputFingerprint = $InputFingerprint
        generatedAt      = (Get-Date).ToString("o")
        outputPaths      = $OutputPaths
    }
    $metadataPath = Get-BuildMetadataPath -MetadataRoot $MetadataRoot -StepName $StepName
    Write-Utf8File -Path $metadataPath -Content ($metadata | ConvertTo-Json -Depth 10)
}

function Invoke-TimedStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Action
    }
    finally {
        $stopwatch.Stop()
        $script:StepTimings.Add([ordered]@{
                label          = $Label
                elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 2)
            }) | Out-Null
        Write-Host ("[build-integrated-package] {0} elapsed: {1:n2}s" -f $Label, $stopwatch.Elapsed.TotalSeconds)
    }
}

function Write-StepTimings {
    Write-Host "[build-integrated-package] Step timings:"
    foreach ($timing in $script:StepTimings) {
        Write-Host ("  - {0}: {1:n2}s" -f [string]$timing.label, [double]$timing.elapsedSeconds)
    }
}

function Get-PathSizeBytes {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $item = Get-Item -LiteralPath $Path
    if (-not $item.PSIsContainer) {
        return [Int64]$item.Length
    }

    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) {
        return [Int64]0
    }
    return [Int64]$sum
}

function Format-ByteSize {
    param(
        [Parameter(Mandatory = $true)]
        [Int64]$Bytes
    )

    if ($Bytes -ge 1GB) {
        return ("{0:n2} GB" -f ($Bytes / 1GB))
    }
    if ($Bytes -ge 1MB) {
        return ("{0:n2} MB" -f ($Bytes / 1MB))
    }
    if ($Bytes -ge 1KB) {
        return ("{0:n2} KB" -f ($Bytes / 1KB))
    }
    return "$Bytes B"
}

function Write-ArtifactSizeSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseRoot,

        [Parameter()]
        [string[]]$PortableRootPaths = @(),

        [Parameter()]
        [string[]]$PortableZipPaths = @(),

        [Parameter()]
        [AllowEmptyString()]
        [string]$PortableZipPath
    )

    $entries = @(
        @{ Label = "release root"; Path = $ReleaseRoot },
        @{ Label = "win-unpacked"; Path = (Join-Path $ReleaseRoot "win-unpacked") },
        @{ Label = "packages"; Path = (Join-Path $ReleaseRoot "packages") }
    )
    foreach ($portableRootPath in $PortableRootPaths) {
        if ([string]::IsNullOrWhiteSpace($portableRootPath)) {
            continue
        }
        $entries += @{ Label = (Split-Path -Leaf $portableRootPath); Path = $portableRootPath }
    }
    $portableZipPathsToSummarize = @($PortableZipPaths)
    if (-not [string]::IsNullOrWhiteSpace($PortableZipPath)) {
        $portableZipPathsToSummarize += $PortableZipPath
    }
    foreach ($portableZipPathToSummarize in $portableZipPathsToSummarize) {
        if ([string]::IsNullOrWhiteSpace($portableZipPathToSummarize)) {
            continue
        }
        $portableZipLabel = if ($portableZipPathsToSummarize.Count -eq 1) {
            "portable zip"
        }
        else {
            Split-Path -Leaf $portableZipPathToSummarize
        }
        $entries += @{ Label = $portableZipLabel; Path = $portableZipPathToSummarize }
    }

    Write-Host "[build-integrated-package] Artifact size summary:"
    foreach ($entry in $entries) {
        $sizeBytes = Get-PathSizeBytes -Path $entry.Path
        if ($null -eq $sizeBytes) {
            continue
        }
        Write-Host ("  - {0}: {1} ({2})" -f $entry.Label, (Format-ByteSize -Bytes $sizeBytes), $entry.Path)
    }
}

function Get-CudaRuntimeMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("cu128", "cu118")]
        [string]$Value
    )

    if ($Value -eq "cu118") {
        return [ordered]@{
            cudaRuntime    = "cu118"
            runtimeVersion = "py311-cu118-v1"
        }
    }

    return [ordered]@{
        cudaRuntime    = "cu128"
        runtimeVersion = "py311-cu128-v1"
    }
}

function Invoke-CudaRuntimeVariantBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("cu128", "cu118")]
        [string]$Variant
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-Profile", $Profile,
        "-Distribution", $Distribution,
        "-CudaRuntime", $Variant,
        "-SevenZipPath", $SevenZipPath,
        "-ZipCompressionLevel", ([string]$ZipCompressionLevel),
        "-SkipReleaseClean"
    )
    if ($SkipPortableZip) {
        $arguments += "-SkipPortableZip"
    }
    if ($SkipPackagedPythonCompile) {
        $arguments += "-SkipPackagedPythonCompile"
    }
    if ($KeepWinUnpacked) {
        $arguments += "-KeepWinUnpacked"
    }
    if ($Offline) {
        $arguments += "-Offline"
    }

    Invoke-NativeStep -Label "Build CUDA runtime variant $Variant" `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments $arguments
}

function Copy-HardLinkedTree {
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
            Copy-HardLinkedTree -SourcePath $entry.FullName -DestinationPath (Join-Path $DestinationPath $entry.Name)
        }
        return
    }

    Ensure-Directory -Path (Split-Path -Parent $DestinationPath)
    if (Test-Path -LiteralPath $DestinationPath) {
        Remove-Item -LiteralPath $DestinationPath -Force
    }
    New-Item -ItemType HardLink -Path $DestinationPath -Target $SourcePath | Out-Null
}

function Sync-BuilderStageInputs {
    $sourceAppRuntime = Join-Path $cudaStageRoot "app-runtime"
    $sourceManifestLock = Join-Path $cudaStageRoot "manifest-lock.json"
    $builderAppRuntime = Join-Path $builderStageRoot "app-runtime"
    $builderManifestLock = Join-Path $builderStageRoot "manifest-lock.json"

    foreach ($requiredPath in @($sourceAppRuntime, $sourceManifestLock)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Builder stage sync prerequisite missing: $requiredPath"
        }
    }

    Remove-PathIfExists -Path $builderAppRuntime -AllowedRoot $builderStageRoot
    Remove-PathIfExists -Path $builderManifestLock -AllowedRoot $builderStageRoot
    Copy-HardLinkedTree -SourcePath $sourceAppRuntime -DestinationPath $builderAppRuntime
    Copy-HardLinkedTree -SourcePath $sourceManifestLock -DestinationPath $builderManifestLock
}

function Remove-WinUnpackedIfNeeded {
    if ($KeepWinUnpacked) {
        Write-Host "[build-integrated-package] Keeping win-unpacked because -KeepWinUnpacked was set."
        return
    }

    Invoke-TimedStep -Label "Clean win-unpacked" -Action {
        Remove-DirectoryIfExists -Path $winUnpackedRoot -AllowedRoot $releaseVersionRoot
    }
    Write-Host "[build-integrated-package] win-unpacked was cleaned: $winUnpackedRoot"
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter()]
        [string[]]$Arguments = @()
    )

    Invoke-TimedStep -Label $Label -Action {
        Write-Host "[build-integrated-package] $Label"
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
}

function Invoke-PackagedPythonCompile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$winUnpackedRoot,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    $packagedPythonExe = Join-Path $winUnpackedRoot "resources\app-runtime\runtime\python\python.exe"
    $packagedBackendDir = Join-Path $winUnpackedRoot "resources\app-runtime\backend"
    $packagedGptSovitsDir = Join-Path $winUnpackedRoot "resources\app-runtime\GPT_SoVITS"
    $packagedSitePackagesDir = Join-Path $winUnpackedRoot "resources\app-runtime\runtime\python\Lib\site-packages"

    foreach ($requiredPath in @($packagedPythonExe, $packagedBackendDir, $packagedGptSovitsDir, $packagedSitePackagesDir)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Packaged Python compile prerequisite missing: $requiredPath"
        }
    }

    Invoke-NativeStep -Label "Compile packaged Python runtime" `
        -WorkingDirectory $WorkingDirectory `
        -FilePath $packagedPythonExe `
        -Arguments @(
            "-m",
            "compileall",
            "-f",
            "-q",
            $packagedBackendDir,
            $packagedGptSovitsDir,
            $packagedSitePackagesDir
        )
}

function Find-SingleArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseRoot,

        [Parameter(Mandatory = $true)]
        [string]$Filter,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [string]$ExcludePattern
    )

    $matches = @(Get-ChildItem -LiteralPath $ReleaseRoot -Filter $Filter -File -Recurse)
    if (-not [string]::IsNullOrWhiteSpace($ExcludePattern)) {
        $matches = @($matches | Where-Object { $_.Name -notmatch $ExcludePattern })
    }
    if ($matches.Count -eq 0) {
        throw "Missing required artifact: $Label ($Filter)"
    }
    if ($matches.Count -gt 1) {
        throw "Expected exactly one artifact for $Label ($Filter), found $($matches.Count)."
    }
    return $matches[0].FullName
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

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Runtime root assembly prerequisite missing: $SourcePath"
    }

    Ensure-Directory -Path $DestinationPath
    Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $DestinationPath $_.Name) -Recurse -Force
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
                Copy-Item -LiteralPath $resourceEntry.FullName -Destination (Join-Path $resourcesDestination $resourceEntry.Name) -Recurse -Force
            }
            continue
        }

        Copy-Item -LiteralPath $entry.FullName -Destination (Join-Path $DestinationRoot $entry.Name) -Recurse -Force
    }
}

function Initialize-InstalledRuntimeRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstalledRootPath,

        [Parameter(Mandatory = $true)]
        [string]$WinUnpackedRoot,

        [Parameter(Mandatory = $true)]
        [string]$BootstrapExePath,

        [Parameter(Mandatory = $true)]
        [string]$UpdateAgentExePath,

        [Parameter(Mandatory = $true)]
        [string]$PackageVersion,

        [Parameter(Mandatory = $true)]
        [string]$ReleaseId,

        [Parameter(Mandatory = $true)]
        [string]$RuntimeVersion,

        [Parameter(Mandatory = $true)]
        [string]$ModelsVersion,

        [Parameter(Mandatory = $true)]
        [string]$PretrainedModelsVersion,

        [Parameter(Mandatory = $true)]
        [string]$StateRootName,

        [Parameter(Mandatory = $true)]
        [string]$PackagesRootName,

        [Parameter()]
        [string]$TutorialPath
    )

    $appRuntimeRoot = Join-Path $WinUnpackedRoot "resources\app-runtime"
    foreach ($requiredPath in @(
            $WinUnpackedRoot,
            $BootstrapExePath,
            $UpdateAgentExePath,
            (Join-Path $WinUnpackedRoot "NeoTTSApp.exe"),
            (Join-Path $appRuntimeRoot "backend"),
            (Join-Path $appRuntimeRoot "frontend-dist"),
            (Join-Path $appRuntimeRoot "config"),
            (Join-Path $appRuntimeRoot "GPT_SoVITS"),
            (Join-Path $appRuntimeRoot "tools"),
            (Join-Path $appRuntimeRoot "runtime"),
            (Join-Path $appRuntimeRoot "models"),
            (Join-Path $appRuntimeRoot "pretrained_models")
        )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Installed runtime root prerequisite missing: $requiredPath"
        }
    }

    Remove-PathIfExists -Path $InstalledRootPath -AllowedRoot $releaseVersionRoot
    Ensure-Directory -Path $InstalledRootPath

    $stateRootPath = Join-Path $InstalledRootPath $StateRootName
    $packagesRootPath = Join-Path $InstalledRootPath $PackagesRootName
    Ensure-Directory -Path $stateRootPath
    Ensure-Directory -Path $packagesRootPath

    Copy-Item -LiteralPath $BootstrapExePath -Destination (Join-Path $InstalledRootPath "NeoTTS.exe") -Force
    Copy-Item -LiteralPath $UpdateAgentExePath -Destination (Join-Path $InstalledRootPath "NeoTTSUpdateAgent.exe") -Force
    if (-not [string]::IsNullOrWhiteSpace($TutorialPath) -and (Test-Path -LiteralPath $TutorialPath)) {
        Copy-Item -LiteralPath $TutorialPath -Destination (Join-Path $InstalledRootPath "使用教程.txt") -Force
    }

    $bootstrapPackageRoot = Join-Path (Join-Path $packagesRootPath "bootstrap") $PackageVersion
    $updateAgentPackageRoot = Join-Path (Join-Path $packagesRootPath "update-agent") $PackageVersion
    $shellPackageRoot = Join-Path (Join-Path $packagesRootPath "shell") $ReleaseId
    $appCorePackageRoot = Join-Path (Join-Path $packagesRootPath "app-core") $ReleaseId
    $runtimePackageRoot = Join-Path (Join-Path $packagesRootPath "runtime") $RuntimeVersion
    $modelsPackageRoot = Join-Path (Join-Path $packagesRootPath "models") $ModelsVersion
    $pretrainedModelsPackageRoot = Join-Path (Join-Path $packagesRootPath "pretrained-models") $PretrainedModelsVersion

    Ensure-Directory -Path $bootstrapPackageRoot
    Ensure-Directory -Path $updateAgentPackageRoot
    Copy-Item -LiteralPath $BootstrapExePath -Destination (Join-Path $bootstrapPackageRoot "NeoTTS.exe") -Force
    Copy-Item -LiteralPath $UpdateAgentExePath -Destination (Join-Path $updateAgentPackageRoot "NeoTTSUpdateAgent.exe") -Force
    Copy-ShellPayload -SourceRoot $WinUnpackedRoot -DestinationRoot $shellPackageRoot
    foreach ($directoryName in @("backend", "frontend-dist", "config", "GPT_SoVITS", "tools")) {
        Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot $directoryName) -DestinationPath (Join-Path $appCorePackageRoot $directoryName)
    }
    Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot "runtime") -DestinationPath (Join-Path $runtimePackageRoot "runtime")
    Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot "models") -DestinationPath (Join-Path $modelsPackageRoot "models")
    Copy-DirectoryContents -SourcePath (Join-Path $appRuntimeRoot "pretrained_models") -DestinationPath (Join-Path $pretrainedModelsPackageRoot "pretrained_models")
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $desktopRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$desktopPackageJsonPath = Join-Path $desktopRoot "package.json"
$desktopPackage = Load-JsonFile -Path $desktopPackageJsonPath
$profilePath = Join-Path $desktopRoot ("packaging\profiles\{0}.v1.json" -f $Profile)
$portableFlavorPath = Join-Path $desktopRoot "packaging\flavors\portable.v1.json"
$installedFlavorPath = Join-Path $desktopRoot "packaging\flavors\installed.v1.json"
$profileConfig = Load-JsonFile -Path $profilePath
$portableFlavor = Load-JsonFile -Path $portableFlavorPath
$installedFlavor = Load-JsonFile -Path $installedFlavorPath
$cudaRuntimeMetadata = Get-CudaRuntimeMetadata -Value $CudaRuntime
$packageVersion = [string]$desktopPackage.version
if ([string]::IsNullOrWhiteSpace($packageVersion)) {
    throw "desktop/package.json version is required for versioned release outputs."
}
$releaseId = Get-NormalizedReleaseId -Value $packageVersion
$runtimeVersion = [string]$cudaRuntimeMetadata.runtimeVersion
$modelsVersion = [string]$profileConfig.layeredPackages.modelsVersion
$pretrainedModelsVersion = [string]$profileConfig.layeredPackages.pretrainedModelsVersion
$portableStateRootName = [string]$portableFlavor.runtimeLayout.stateRoot
$portablePackagesRootName = [string]$portableFlavor.runtimeLayout.packagesRoot
$installedStateRootName = [string]$installedFlavor.runtimeLayout.stateRoot
$installedPackagesRootName = [string]$installedFlavor.runtimeLayout.packagesRoot
$releaseRoot = Join-Path $desktopRoot "release"
$releaseVersionRoot = Join-Path $releaseRoot $packageVersion
$stageRuntimeScript = Join-Path $scriptDir "stage-runtime.ps1"
$assemblePortableScript = Join-Path $scriptDir "assemble-portable.ps1"
$buildLayeredReleaseScript = Join-Path $scriptDir "build-layered-release.ps1"
$innoSetupScript = Join-Path $desktopRoot "packaging\installers\windows-installer.iss"
$setupIconPath = Join-Path $projectRoot "frontend\public\512.ico"
$tutorialSourcePath = Join-Path $projectRoot "使用教程.txt"
$buildBootstrapScript = Join-Path $projectRoot "launcher\build-bootstrap.ps1"
$launcherDistRoot = Join-Path $projectRoot "launcher\dist"
$launcherBootstrapDistPath = Join-Path $launcherDistRoot "NeoTTS.exe"
$launcherUpdateAgentDistPath = Join-Path $launcherDistRoot "NeoTTSUpdateAgent.exe"
$winUnpackedRoot = Join-Path $releaseVersionRoot "win-unpacked"
$winUnpackedBootstrapExe = Join-Path $winUnpackedRoot "NeoTTS.exe"
$winUnpackedShellExe = Join-Path $winUnpackedRoot "NeoTTSApp.exe"
$winUnpackedUpdateAgentExe = Join-Path $winUnpackedRoot "NeoTTSUpdateAgent.exe"
$tutorialTargetPath = Join-Path $winUnpackedRoot "使用教程.txt"
$installerBaseName = "NeoTTS-Setup-$packageVersion"
$installedRootPath = Join-Path $releaseVersionRoot "NeoTTS-InstalledRoot"
$portableRootDefaultPath = Join-Path $releaseVersionRoot "NeoTTS-Portable-$CudaRuntime"
$portableZipDefaultPath = Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion-$CudaRuntime.zip"
$builderStageRoot = Join-Path $desktopRoot ".stage"
$cudaStageRoot = Join-Path $builderStageRoot $CudaRuntime
$cacheRoot = Join-Path $desktopRoot ".cache"
$buildMetadataRoot = Join-Path $cacheRoot "build-metadata"
$frontendDistRoot = Join-Path $frontendRoot "dist"
$desktopDistRoot = Join-Path $desktopRoot "dist"
$desktopSourceRoot = Join-Path $desktopRoot "src"

foreach ($requiredPath in @($frontendRoot, $stageRuntimeScript, $buildBootstrapScript, $buildLayeredReleaseScript, $desktopPackageJsonPath, $profilePath, $portableFlavorPath, $installedFlavorPath, $tutorialSourcePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Build prerequisite missing: $requiredPath"
    }
}
if ($Distribution -eq "portable") {
    foreach ($requiredPath in @($assemblePortableScript)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Build prerequisite missing: $requiredPath"
        }
    }
}
else {
    foreach ($requiredPath in @($innoSetupScript, $setupIconPath, $InnoSetupCompiler)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Build prerequisite missing: $requiredPath"
        }
    }
}

Ensure-Directory -Path $buildMetadataRoot
Ensure-Directory -Path $releaseRoot

foreach ($requiredValue in @(
        @{ Label = "layeredPackages.runtimeVersion"; Value = $runtimeVersion },
        @{ Label = "layeredPackages.modelsVersion"; Value = $modelsVersion },
        @{ Label = "layeredPackages.pretrainedModelsVersion"; Value = $pretrainedModelsVersion },
        @{ Label = "portable runtimeLayout.stateRoot"; Value = $portableStateRootName },
        @{ Label = "portable runtimeLayout.packagesRoot"; Value = $portablePackagesRootName },
        @{ Label = "installed runtimeLayout.stateRoot"; Value = $installedStateRootName },
        @{ Label = "installed runtimeLayout.packagesRoot"; Value = $installedPackagesRootName }
    )) {
    if ([string]::IsNullOrWhiteSpace([string]$requiredValue.Value)) {
        throw "Build prerequisite missing metadata: $($requiredValue.Label)"
    }
}

if ($BuildCudaRuntimeVariants) {
    if ($Distribution -ne "portable") {
        throw "-BuildCudaRuntimeVariants only supports portable distribution."
    }
    if ($BuildUpdatePackages) {
        throw "-BuildUpdatePackages cannot be combined with -BuildCudaRuntimeVariants because the current update manifest path is not CUDA-runtime scoped."
    }
    if (-not $SkipReleaseClean) {
        Write-Host "[build-integrated-package] Cleaning current version release outputs..."
        Remove-DirectoryIfExists -Path $releaseVersionRoot -AllowedRoot $releaseRoot
    }
    Invoke-CudaRuntimeVariantBuild -Variant "cu128"
    Invoke-CudaRuntimeVariantBuild -Variant "cu118"
    Write-StepTimings
    Write-ArtifactSizeSummary -ReleaseRoot $releaseVersionRoot -PortableRootPaths @(
        (Join-Path $releaseVersionRoot "NeoTTS-Portable-cu128"),
        (Join-Path $releaseVersionRoot "NeoTTS-Portable-cu118")
    ) -PortableZipPaths @(
        (Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion-cu128.zip"),
        (Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion-cu118.zip")
    )
    Write-Host "[build-integrated-package] CUDA runtime variant artifacts ready:"
    if ($SkipPortableZip) {
        Write-Host "  - cu128 root: $(Join-Path $releaseVersionRoot "NeoTTS-Portable-cu128")"
        Write-Host "  - cu118 root: $(Join-Path $releaseVersionRoot "NeoTTS-Portable-cu118")"
    }
    else {
        Write-Host "  - cu128 zip:  $(Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion-cu128.zip")"
        Write-Host "  - cu118 zip:  $(Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion-cu118.zip")"
    }
    return
}

if (-not $SkipReleaseClean) {
    Write-Host "[build-integrated-package] Cleaning current version release outputs..."
    Remove-DirectoryIfExists -Path $releaseVersionRoot -AllowedRoot $releaseRoot
}

if (-not (Test-Path -LiteralPath $desktopSourceRoot)) {
    throw "Build prerequisite missing: $desktopSourceRoot"
}

$frontendBuildInputPaths = @(
    (Join-Path $frontendRoot "src"),
    (Join-Path $frontendRoot "public"),
    (Join-Path $frontendRoot "index.html"),
    (Join-Path $frontendRoot "package.json"),
    (Join-Path $frontendRoot "package-lock.json"),
    (Join-Path $frontendRoot "postcss.config.js"),
    (Join-Path $frontendRoot "tailwind.config.ts"),
    (Join-Path $frontendRoot "tsconfig.json"),
    (Join-Path $frontendRoot "tsconfig.app.json"),
    (Join-Path $frontendRoot "tsconfig.node.json"),
    (Join-Path $frontendRoot "vite.config.ts")
)
$frontendBuildFingerprint = Get-FingerprintFromPaths -RootPath $frontendRoot -Paths $frontendBuildInputPaths
$frontendBuildRequiredPaths = @(
    $frontendDistRoot,
    (Join-Path $frontendDistRoot "index.html")
)
$reuseFrontendBuild = Test-BuildStepReusable `
    -MetadataRoot $buildMetadataRoot `
    -StepName "frontend-build" `
    -InputFingerprint $frontendBuildFingerprint `
    -RequiredPaths $frontendBuildRequiredPaths
if ($reuseFrontendBuild) {
    Write-Host "[build-integrated-package] Reusing frontend build outputs..."
}
else {
    Invoke-NativeStep -Label "Build frontend" `
        -WorkingDirectory $frontendRoot `
        -FilePath "npm.cmd" `
        -Arguments @("run", "build")
    Write-BuildStepMetadata `
        -MetadataRoot $buildMetadataRoot `
        -StepName "frontend-build" `
        -InputFingerprint $frontendBuildFingerprint `
        -OutputPaths $frontendBuildRequiredPaths
}

$desktopBuildInputPaths = @(
    $desktopSourceRoot,
    (Join-Path $desktopRoot "package.json"),
    (Join-Path $desktopRoot "package-lock.json"),
    (Join-Path $desktopRoot "tsconfig.json")
)
$desktopBuildFingerprint = Get-FingerprintFromPaths -RootPath $desktopRoot -Paths $desktopBuildInputPaths
$desktopBuildRequiredPaths = New-Object System.Collections.Generic.List[string]
$desktopBuildRequiredPaths.Add($desktopDistRoot) | Out-Null
foreach ($sourceFile in (Get-ChildItem -LiteralPath $desktopSourceRoot -Recurse -File -Filter *.ts | Where-Object { $_.Name -notlike "*.d.ts" })) {
    $relativePath = (Get-RelativePathNormalized -BasePath $desktopSourceRoot -TargetPath $sourceFile.FullName).Replace("/", "\")
    $compiledRelativePath = [System.IO.Path]::ChangeExtension($relativePath, ".js")
    $desktopBuildRequiredPaths.Add((Join-Path $desktopDistRoot $compiledRelativePath)) | Out-Null
}
$reuseDesktopBuild = Test-BuildStepReusable `
    -MetadataRoot $buildMetadataRoot `
    -StepName "desktop-build" `
    -InputFingerprint $desktopBuildFingerprint `
    -RequiredPaths @($desktopBuildRequiredPaths)
if ($reuseDesktopBuild) {
    Write-Host "[build-integrated-package] Reusing desktop TypeScript build outputs..."
}
else {
    Invoke-NativeStep -Label "Build desktop TypeScript" `
        -WorkingDirectory $desktopRoot `
        -FilePath "npm.cmd" `
        -Arguments @("run", "build")
    Write-BuildStepMetadata `
        -MetadataRoot $buildMetadataRoot `
        -StepName "desktop-build" `
        -InputFingerprint $desktopBuildFingerprint `
        -OutputPaths @($desktopBuildRequiredPaths)
}

$stageRuntimeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $stageRuntimeScript,
    "-Profile", $Profile,
    "-Flavor", $Distribution,
    "-CudaRuntime", $CudaRuntime,
    "-StageRoot", $cudaStageRoot,
    "-SevenZipPath", $SevenZipPath
)
if ($Offline) {
    $stageRuntimeArgs += "-Offline"
}
Invoke-NativeStep -Label "Stage runtime" `
    -WorkingDirectory $desktopRoot `
    -FilePath "powershell.exe" `
    -Arguments $stageRuntimeArgs

Invoke-TimedStep -Label "Sync builder stage inputs" -Action {
    Sync-BuilderStageInputs
}

Invoke-NativeStep -Label "Build bootstrap launchers" `
    -WorkingDirectory $projectRoot `
    -FilePath "powershell.exe" `
    -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $buildBootstrapScript
    )

$builderFailed = $false
$builderFailure = $null
try {
    Invoke-NativeStep -Label "Build Windows dir artifact" `
        -WorkingDirectory $desktopRoot `
        -FilePath "npm.cmd" `
        -Arguments @("run", "package:builder")
}
catch {
    $builderFailed = $true
    $builderFailure = $_
    Write-Warning "electron-builder returned a non-zero exit code; falling back to artifact validation."
}

foreach ($requiredPath in @($winUnpackedRoot, $winUnpackedShellExe, $launcherBootstrapDistPath, $launcherUpdateAgentDistPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        if ($builderFailed) {
            throw $builderFailure
        }
        throw "Integrated package validation failed after builder: missing $requiredPath"
    }
}

Copy-Item -LiteralPath $launcherBootstrapDistPath -Destination $winUnpackedBootstrapExe -Force
Copy-Item -LiteralPath $launcherUpdateAgentDistPath -Destination $winUnpackedUpdateAgentExe -Force

foreach ($requiredPath in @($winUnpackedBootstrapExe, $winUnpackedShellExe, $winUnpackedUpdateAgentExe)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Integrated package validation failed after launcher injection: missing $requiredPath"
    }
}

Copy-Item -LiteralPath $tutorialSourcePath -Destination $tutorialTargetPath -Force
if (-not (Test-Path -LiteralPath $tutorialTargetPath)) {
    throw "Integrated package validation failed after tutorial copy: missing $tutorialTargetPath"
}

if ($SkipPackagedPythonCompile) {
    Write-Host "[build-integrated-package] Skipping packaged Python compile because -SkipPackagedPythonCompile was set."
}
else {
    Invoke-PackagedPythonCompile -WinUnpackedRoot $winUnpackedRoot -WorkingDirectory $desktopRoot
}

if ($BuildUpdatePackages) {
    Invoke-NativeStep -Label "Build layered release artifacts" `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $buildLayeredReleaseScript,
            "-Profile", $Profile,
            "-Distribution", $Distribution,
            "-ReleaseRoot", $releaseVersionRoot,
            "-StageRoot", $cudaStageRoot,
            "-WinUnpackedRoot", $winUnpackedRoot,
            "-BootstrapDistRoot", $launcherDistRoot,
            "-RuntimeVersionOverride", $runtimeVersion,
            "-SevenZipPath", $SevenZipPath,
            "-ZipCompressionLevel", ([string]$ZipCompressionLevel),
            "-KeepExistingPackages",
            "-SkipStageRuntime",
            "-SkipBootstrapBuild",
            "-SkipShellBuild"
        )
}
else {
    Write-Host "[build-integrated-package] Skipping layered release artifacts because -BuildUpdatePackages was not set."
}

if ($Distribution -eq "portable") {
    $portableLabel = if ($SkipPortableZip) { "Assemble portable root (skip zip)" } else { "Assemble portable zip" }
    $assemblePortableArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $assemblePortableScript,
        "-Profile", $Profile,
        "-ReleaseRoot", $releaseVersionRoot,
        "-PortableRoot", $portableRootDefaultPath,
        "-PortableZipPath", $portableZipDefaultPath,
        "-RuntimeVersionOverride", $runtimeVersion,
        "-SevenZipPath", $SevenZipPath,
        "-ZipCompressionLevel", ([string]$ZipCompressionLevel)
    )
    if ($SkipPortableZip) {
        $assemblePortableArgs += "-SkipZip"
    }
    Invoke-NativeStep -Label $portableLabel `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments $assemblePortableArgs

    $portableRootPath = $portableRootDefaultPath
    if ($SkipPortableZip) {
        foreach ($requiredPath in @(
                $winUnpackedBootstrapExe,
                $winUnpackedShellExe,
                $winUnpackedUpdateAgentExe,
                $portableRootPath,
                (Join-Path $portableRootPath "NeoTTS.exe"),
                (Join-Path $portableRootPath "NeoTTSUpdateAgent.exe"),
                (Join-Path $portableRootPath "portable.flag"),
                (Join-Path $portableRootPath "$portableStateRootName\current.json"),
                (Join-Path $portableRootPath "$portablePackagesRootName\shell\$releaseId\NeoTTSApp.exe"),
                (Join-Path $portableRootPath "$portablePackagesRootName\app-core\$releaseId\backend"),
                (Join-Path $portableRootPath "使用教程.txt")
            )) {
            if (-not (Test-Path -LiteralPath $requiredPath)) {
                throw "Portable package validation failed: missing $requiredPath"
            }
        }
        if (Test-Path -LiteralPath (Join-Path $portableRootPath "NeoTTSApp.exe")) {
            throw "Portable package validation failed: NeoTTSApp.exe should not remain at the portable root."
        }
        Remove-WinUnpackedIfNeeded
        Write-StepTimings
        Write-ArtifactSizeSummary -ReleaseRoot $releaseVersionRoot -PortableRootPaths @($portableRootPath)
        Write-Host "[build-integrated-package] Artifacts ready:"
        Write-Host "  - portable root: $portableRootPath"
        Write-Host "  - release root:  $releaseVersionRoot"
        Write-Host "  - note:          zip packaging was skipped"
    }
    else {
        $portableZipPath = $portableZipDefaultPath
        if (-not (Test-Path -LiteralPath $portableZipPath)) {
            throw "Missing required artifact: portable zip ($portableZipPath)"
        }
        foreach ($requiredPath in @($winUnpackedBootstrapExe, $winUnpackedShellExe, $winUnpackedUpdateAgentExe, $tutorialTargetPath, $portableZipPath)) {
            if (-not (Test-Path -LiteralPath $requiredPath)) {
                throw "Portable package validation failed: missing $requiredPath"
            }
        }

        Remove-WinUnpackedIfNeeded
        Write-StepTimings
        Write-ArtifactSizeSummary -ReleaseRoot $releaseVersionRoot -PortableRootPaths @($portableRootDefaultPath) -PortableZipPath $portableZipPath
        Write-Host "[build-integrated-package] Artifacts ready:"
        Write-Host "  - portable zip: $portableZipPath"
        Write-Host "  - release root: $releaseVersionRoot"
        Write-Host "  - installer:    run 'npm run package:installed' when needed"
    }
}
else {
    Initialize-InstalledRuntimeRoot `
        -InstalledRootPath $installedRootPath `
        -WinUnpackedRoot $winUnpackedRoot `
        -BootstrapExePath $winUnpackedBootstrapExe `
        -UpdateAgentExePath $winUnpackedUpdateAgentExe `
        -PackageVersion $packageVersion `
        -ReleaseId $releaseId `
        -RuntimeVersion $runtimeVersion `
        -ModelsVersion $modelsVersion `
        -PretrainedModelsVersion $pretrainedModelsVersion `
        -StateRootName $installedStateRootName `
        -PackagesRootName $installedPackagesRootName `
        -TutorialPath $tutorialTargetPath

    Invoke-NativeStep -Label "Build Windows installer with Inno Setup" `
        -WorkingDirectory $desktopRoot `
        -FilePath $InnoSetupCompiler `
        -Arguments @(
            "/Qp",
            "/DAppId=com.neo-tts.desktop",
            "/DAppName=NeoTTS",
            "/DAppVersion=$packageVersion",
            "/DAppExeName=NeoTTS.exe",
            "/DReleaseId=$releaseId",
            "/DBootstrapVersion=$packageVersion",
            "/DUpdateAgentVersion=$packageVersion",
            "/DRuntimeVersion=$runtimeVersion",
            "/DModelsVersion=$modelsVersion",
            "/DPretrainedModelsVersion=$pretrainedModelsVersion",
            "/DStateRoot=$installedStateRootName",
            "/DPackagesRoot=$installedPackagesRootName",
            "/DCurrentStateRelativePath=$installedStateRootName\\current.json",
            "/DSourceRoot=$installedRootPath",
            "/DOutputDir=$releaseVersionRoot",
            "/DOutputBaseFilename=$installerBaseName",
            "/DSetupIconFile=$setupIconPath",
            $innoSetupScript
        )

    $installerPath = Find-SingleArtifact -ReleaseRoot $releaseVersionRoot -Filter "*Setup*.exe" -Label "Windows installer" -ExcludePattern "__uninstaller"
    foreach ($requiredPath in @(
            $installedRootPath,
            (Join-Path $installedRootPath "NeoTTS.exe"),
            (Join-Path $installedRootPath "NeoTTSUpdateAgent.exe"),
            (Join-Path $installedRootPath $installedStateRootName),
            (Join-Path $installedRootPath "$installedPackagesRootName\shell\$releaseId\NeoTTSApp.exe"),
            (Join-Path $installedRootPath "$installedPackagesRootName\app-core\$releaseId\backend"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-hubert-base\config.json"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-hubert-base\preprocessor_config.json"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-hubert-base\pytorch_model.bin"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-roberta-wwm-ext-large\config.json"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-roberta-wwm-ext-large\pytorch_model.bin"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\chinese-roberta-wwm-ext-large\tokenizer.json"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\neuro2\neuro2-e4.ckpt"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\neuro2\neuro2_e4_s424.pth"),
            (Join-Path $installedRootPath "$installedPackagesRootName\models\$modelsVersion\models\builtin\neuro2\audio1.wav"),
            (Join-Path $installedRootPath "$installedPackagesRootName\pretrained-models\$pretrainedModelsVersion\pretrained_models\sv\pretrained_eres2netv2w24s4ep4.ckpt"),
            (Join-Path $installedRootPath "$installedPackagesRootName\pretrained-models\$pretrainedModelsVersion\pretrained_models\fast_langdetect\lid.176.bin"),
            $installerPath
        )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Installed package validation failed after Inno Setup: missing $requiredPath"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $installedRootPath "NeoTTSApp.exe")) {
        throw "Installed package validation failed: NeoTTSApp.exe should not remain at the installed runtime root."
    }

    Remove-WinUnpackedIfNeeded
    Write-StepTimings
    Write-ArtifactSizeSummary -ReleaseRoot $releaseVersionRoot
    Write-Host "[build-integrated-package] Artifacts ready:"
    Write-Host "  - installer:    $installerPath"
    Write-Host "  - install root: $installedRootPath"
    Write-Host "  - release root: $releaseVersionRoot"
    Write-Host "  - portable zip: run 'npm run package' when needed"
}
