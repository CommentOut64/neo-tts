param(
    [ValidateSet("default")]
    [string]$Profile = "default",

    [ValidateSet("installed", "portable")]
    [string]$Flavor = "installed",

    [string]$StageRoot,

    [switch]$Offline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:UV_HTTP_TIMEOUT) {
    $env:UV_HTTP_TIMEOUT = "300"
}

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

function Load-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

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
        [AllowEmptyString()]
        [string]$Content
    )

    Ensure-Directory -Path (Split-Path -Parent $Path)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
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

function Resolve-LayerPackage {
    param(
        [Parameter()]
        [AllowEmptyString()]
        [string]$LayerPackage
    )

    if ([string]::IsNullOrWhiteSpace($LayerPackage)) {
        return $null
    }

    $normalized = $LayerPackage.Trim()
    if ($normalized -notin @("app-core", "runtime", "models", "pretrained-models")) {
        throw "Unsupported layerPackage '$normalized'."
    }
    return $normalized
}

function Add-LockEntry {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$Entries,

        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$Category,

        [Parameter(Mandatory = $true)]
        [bool]$Required,

        [Parameter(Mandatory = $true)]
        [string]$OverwritePolicy,

        [Parameter()]
        [AllowEmptyCollection()]
        [object[]]$ProfileTags,

        [Parameter()]
        [AllowEmptyString()]
        [string]$LayerPackage
    )

    $Entries.Add([ordered]@{
            source          = $Source
            destination     = $Destination
            category        = $Category
            required        = $Required
            overwritePolicy = $OverwritePolicy
            profileTags     = $ProfileTags
            layerPackage    = Resolve-LayerPackage -LayerPackage $LayerPackage
        }) | Out-Null
}

function Get-FilteredFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath
    )

    $root = Get-Item -LiteralPath $SourcePath
    if (-not $root.PSIsContainer) {
        return @($root)
    }

    return Get-ChildItem -LiteralPath $SourcePath -Recurse -File | Where-Object {
        $_.Extension -notin @(".pyc", ".pyo") -and
        $_.FullName -notmatch "\\__pycache__(\\|$)"
    }
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
        $fileSha256 = Get-FileSha256 -Path $item.FullName
        return Get-TextSha256 -Text ("file|{0}|{1}" -f $item.Name, $fileSha256)
    }

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($file in (Get-FilteredFiles -SourcePath $Path | Sort-Object FullName)) {
        $relativePath = Get-RelativePathNormalized -BasePath $Path -TargetPath $file.FullName
        $lines.Add(("{0}|{1}|{2}" -f $relativePath, $file.Length, $file.LastWriteTimeUtc.Ticks)) | Out-Null
    }
    return Get-TextSha256 -Text (($lines -join "`n"))
}

function Get-FingerprintFromStrings {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Values
    )

    return Get-TextSha256 -Text (($Values | Sort-Object) -join "`n")
}

function Get-PartitionMetadataPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$PartitionName
    )

    return Join-Path $MetadataRoot ("{0}.json" -f $PartitionName)
}

function Get-PartitionMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$PartitionName
    )

    $metadataPath = Get-PartitionMetadataPath -MetadataRoot $MetadataRoot -PartitionName $PartitionName
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        return $null
    }
    return Load-JsonFile -Path $metadataPath
}

function Test-PartitionReusable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$PartitionName,

        [Parameter(Mandatory = $true)]
        [string]$InputFingerprint,

        [Parameter(Mandatory = $true)]
        [string[]]$RequiredPaths
    )

    $metadataPath = Get-PartitionMetadataPath -MetadataRoot $MetadataRoot -PartitionName $PartitionName
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

function Write-PartitionMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetadataRoot,

        [Parameter(Mandatory = $true)]
        [string]$PartitionName,

        [Parameter(Mandatory = $true)]
        [string]$InputFingerprint,

        [Parameter(Mandatory = $true)]
        [string[]]$OutputPaths
    )

    Ensure-Directory -Path $MetadataRoot
    $metadata = [ordered]@{
        schemaVersion    = 1
        partition        = $PartitionName
        inputFingerprint = $InputFingerprint
        generatedAt      = (Get-Date).ToString("o")
        outputPaths      = $OutputPaths
    }
    $metadataPath = Get-PartitionMetadataPath -MetadataRoot $MetadataRoot -PartitionName $PartitionName
    Write-Utf8File -Path $metadataPath -Content ($metadata | ConvertTo-Json -Depth 10)
}

function Get-ManifestEntriesFingerprint {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Entries,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($entry in @($Entries | Sort-Object destination, source, category)) {
        $sourcePath = Join-Path $ProjectRoot ([string]$entry.source)
        $lines.Add((
                "{0}|{1}|{2}|{3}|{4}|{5}" -f
                [string]$entry.source,
                [string]$entry.destination,
                [string]$entry.category,
                [string]$entry.layerPackage,
                [string]$entry.overwritePolicy,
                [bool]$entry.required,
                (Get-PathFingerprint -Path $sourcePath)
            )) | Out-Null
    }
    return Get-TextSha256 -Text (($lines -join "`n"))
}

function Copy-StagedEntry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,

        [Parameter(Mandatory = $true)]
        [string]$Category,

        [Parameter(Mandatory = $true)]
        [bool]$Required,

        [Parameter(Mandatory = $true)]
        [string]$OverwritePolicy,

        [Parameter()]
        [AllowEmptyCollection()]
        [object[]]$ProfileTags,

        [Parameter()]
        [AllowEmptyString()]
        [string]$LayerPackage,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$StageRoot,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$Entries,

        [switch]$SkipLockEntries,

        [switch]$SkipCopy
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        if ($Required) {
            throw "Missing required source path: $SourcePath"
        }
        if (-not $SkipCopy) {
            Remove-PathIfExists -Path $DestinationPath -AllowedRoot $StageRoot
        }
        return
    }

    $sourceItem = Get-Item -LiteralPath $SourcePath
    if ($sourceItem.PSIsContainer) {
        $files = Get-FilteredFiles -SourcePath $SourcePath
        if (-not $SkipCopy) {
            Remove-PathIfExists -Path $DestinationPath -AllowedRoot $StageRoot
            Ensure-Directory -Path $DestinationPath
        }
        foreach ($file in $files) {
            $relativePath = Get-RelativePathNormalized -BasePath $SourcePath -TargetPath $file.FullName
            $targetPath = Join-Path $DestinationPath $relativePath
            if (-not $SkipCopy) {
                Ensure-Directory -Path (Split-Path -Parent $targetPath)
                Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
            }
            if (-not $SkipLockEntries) {
                $sourceLabel = Get-RelativePathNormalized -BasePath $ProjectRoot -TargetPath $file.FullName
                $destinationLabel = Get-RelativePathNormalized -BasePath $StageRoot -TargetPath $targetPath
                Add-LockEntry -Entries $Entries `
                    -Source $sourceLabel `
                    -Destination $destinationLabel `
                    -Category $Category `
                    -Required $Required `
                    -OverwritePolicy $OverwritePolicy `
                    -ProfileTags $ProfileTags `
                    -LayerPackage $LayerPackage
            }
        }
        return
    }

    if (-not $SkipCopy) {
        Ensure-Directory -Path (Split-Path -Parent $DestinationPath)
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    }
    if (-not $SkipLockEntries) {
        Add-LockEntry -Entries $Entries `
            -Source (Get-RelativePathNormalized -BasePath $ProjectRoot -TargetPath $SourcePath) `
            -Destination (Get-RelativePathNormalized -BasePath $StageRoot -TargetPath $DestinationPath) `
            -Category $Category `
            -Required $Required `
            -OverwritePolicy $OverwritePolicy `
            -ProfileTags $ProfileTags `
            -LayerPackage $LayerPackage
    }
}

function Remove-BlacklistedPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$BlacklistEntries
    )

    foreach ($relativePath in $BlacklistEntries) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }
        $targetPath = Join-Path $RuntimeRoot $relativePath
        if (Test-Path -LiteralPath $targetPath) {
            Remove-Item -LiteralPath $targetPath -Recurse -Force
        }
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $desktopRoot
$pythonInstallRoot = (& uv python dir).Trim()
$desktopPackageJsonPath = Join-Path $desktopRoot "package.json"
$manifestPath = Join-Path $desktopRoot "packaging\manifests\base.v1.json"
$profilePath = Join-Path $desktopRoot ("packaging\profiles\{0}.v1.json" -f $Profile)
$flavorPath = Join-Path $desktopRoot ("packaging\flavors\{0}.v1.json" -f $Flavor)
$pythonBlacklistPath = Join-Path $desktopRoot "packaging\python-blacklist.txt"
$pythonRuntimePrunePath = Join-Path $desktopRoot "packaging\python-runtime-prune.txt"
$frontendDistPath = Join-Path $projectRoot "frontend\dist"
$uvLockPath = Join-Path $projectRoot "uv.lock"
$pyprojectPath = Join-Path $projectRoot "pyproject.toml"
$nltkPayloadRoot = Join-Path $projectRoot "launcher\internal\nltkpatcher\payload\nltk_data"
$cmudictPayloadPath = Join-Path $nltkPayloadRoot "corpora\cmudict.zip"
$averagedPerceptronTaggerPayloadPath = Join-Path $nltkPayloadRoot "taggers\averaged_perceptron_tagger.zip"
$averagedPerceptronTaggerEngPayloadPath = Join-Path $nltkPayloadRoot "taggers\averaged_perceptron_tagger_eng.zip"

if ([string]::IsNullOrWhiteSpace($StageRoot)) {
    $StageRoot = Join-Path $desktopRoot ".stage"
}

$stageRootPath = Get-FullPath -Path $StageRoot
Assert-PathWithinRoot -Path $stageRootPath -Root $desktopRoot

$requiredInputs = @(
    @{ Path = $desktopPackageJsonPath; Label = "desktop/package.json" }
    @{ Path = $manifestPath; Label = "base manifest" }
    @{ Path = $profilePath; Label = "profile" }
    @{ Path = $flavorPath; Label = "flavor" }
    @{ Path = $pythonBlacklistPath; Label = "python blacklist" }
    @{ Path = $pythonRuntimePrunePath; Label = "python runtime prune list" }
    @{ Path = $frontendDistPath; Label = "frontend/dist" }
    @{ Path = $uvLockPath; Label = "uv.lock" }
    @{ Path = $pyprojectPath; Label = "pyproject.toml" }
    @{ Path = $cmudictPayloadPath; Label = "nltk cmudict payload" }
    @{ Path = $averagedPerceptronTaggerPayloadPath; Label = "nltk averaged_perceptron_tagger payload" }
    @{ Path = $averagedPerceptronTaggerEngPayloadPath; Label = "nltk averaged_perceptron_tagger_eng payload" }
)

$missingInputs = @($requiredInputs | Where-Object { -not (Test-Path -LiteralPath $_.Path) })
if ($missingInputs.Count -gt 0) {
    $details = ($missingInputs | ForEach-Object { " - $($_.Label): $($_.Path)" }) -join [Environment]::NewLine
    throw "Runtime staging prerequisites missing:$([Environment]::NewLine)$details"
}

$baseManifest = Load-JsonFile -Path $manifestPath
$profileConfig = Load-JsonFile -Path $profilePath
$flavorConfig = Load-JsonFile -Path $flavorPath
$desktopPackage = Load-JsonFile -Path $desktopPackageJsonPath
$pythonBlacklistEntries = Get-Content -LiteralPath $pythonBlacklistPath | ForEach-Object { $_.Trim() } | Where-Object {
    $_ -and -not $_.StartsWith("#")
}
$pythonRuntimePruneEntries = Get-Content -LiteralPath $pythonRuntimePrunePath | ForEach-Object { $_.Trim() } | Where-Object {
    $_ -and -not $_.StartsWith("#")
}
$pythonRuntimePruneFingerprint = if ($pythonRuntimePruneEntries.Count -gt 0) {
    Get-FingerprintFromStrings -Values $pythonRuntimePruneEntries
}
else {
    "none"
}

if ([string]$profileConfig.profileId -eq "default.v1") {
    $defaultBuiltinVoiceIds = @($profileConfig.builtinVoices | ForEach-Object { [string]$_.voiceId })
    if ($defaultBuiltinVoiceIds.Count -ne 1 -or $defaultBuiltinVoiceIds[0] -ne "neuro2") {
        throw "Profile 'default.v1' must package exactly one builtin voice: neuro2."
    }
}

if ($flavorConfig.distributionKind -ne $Flavor) {
    throw "Flavor metadata mismatch: expected '$Flavor', got '$($flavorConfig.distributionKind)'."
}

$appRuntimeRoot = Join-Path $stageRootPath "app-runtime"
$frontendStagePath = Join-Path $appRuntimeRoot "frontend-dist"
$backendStagePath = Join-Path $appRuntimeRoot "backend"
$gptSovitsStagePath = Join-Path $appRuntimeRoot "GPT_SoVITS"
$runtimePythonDir = Join-Path $appRuntimeRoot "runtime\python"
$builtinModelDir = Join-Path $appRuntimeRoot "models\builtin"
$configDir = Join-Path $appRuntimeRoot "config"
$cacheRoot = Join-Path $desktopRoot ".cache"
$wheelhouseDir = Join-Path $cacheRoot "wheelhouse"
$runtimePythonCacheRoot = Join-Path $cacheRoot "runtime-python"
$requirementsCacheRoot = Join-Path $cacheRoot "requirements"
$stagingMetadataRoot = Join-Path $cacheRoot "staging-metadata"
$manifestLockPath = Join-Path $stageRootPath "manifest-lock.json"
$wheelhouseMetadataPath = Join-Path $wheelhouseDir "wheelhouse-lock.json"
$portableMarkerPath = Join-Path $stageRootPath "portable.flag"
$lockEntries = New-Object 'System.Collections.Generic.List[object]'

$null = @(
    $stageRootPath,
    $appRuntimeRoot,
    $builtinModelDir,
    $configDir,
    $cacheRoot,
    $wheelhouseDir,
    $runtimePythonCacheRoot,
    $requirementsCacheRoot,
    $stagingMetadataRoot
) | ForEach-Object {
    Ensure-Directory -Path $_
}

if ($Flavor -eq "portable") {
    Write-Utf8File -Path $portableMarkerPath -Content ""
    Add-LockEntry -Entries $lockEntries `
        -Source "generated://portable.flag" `
        -Destination (Get-RelativePathNormalized -BasePath $stageRootPath -TargetPath $portableMarkerPath) `
        -Category "portable-flag" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @($Flavor)
}
else {
    Remove-PathIfExists -Path $portableMarkerPath -AllowedRoot $stageRootPath
}

$frontendPartitionName = "frontend-dist"
$frontendFingerprint = Get-FingerprintFromStrings -Values @(
    "frontend-dist",
    (Get-PathFingerprint -Path $frontendDistPath)
)
$reuseFrontendPartition = Test-PartitionReusable `
    -MetadataRoot $stagingMetadataRoot `
    -PartitionName $frontendPartitionName `
    -InputFingerprint $frontendFingerprint `
    -RequiredPaths @($frontendStagePath)
Write-Host ("[stage-runtime] {0} frontend dist..." -f $(if ($reuseFrontendPartition) { "Reusing" } else { "Rebuilding" }))
Copy-StagedEntry -SourcePath $frontendDistPath `
    -DestinationPath $frontendStagePath `
    -Category "frontend-dist" `
    -Required $true `
    -OverwritePolicy "replace" `
    -ProfileTags @() `
    -LayerPackage "app-core" `
    -ProjectRoot $projectRoot `
    -StageRoot $stageRootPath `
    -Entries $lockEntries `
    -SkipCopy:$reuseFrontendPartition
if (-not $reuseFrontendPartition) {
    Write-PartitionMetadata `
        -MetadataRoot $stagingMetadataRoot `
        -PartitionName $frontendPartitionName `
        -InputFingerprint $frontendFingerprint `
        -OutputPaths @($frontendStagePath)
}

$manifestEntries = @($baseManifest.entries)
$manifestPartitionName = "manifest-resources"
$manifestFingerprint = Get-ManifestEntriesFingerprint -Entries $manifestEntries -ProjectRoot $projectRoot
$manifestOutputPaths = @($manifestEntries | ForEach-Object { Join-Path $appRuntimeRoot ([string]$_.destination) })
$reuseManifestPartition = Test-PartitionReusable `
    -MetadataRoot $stagingMetadataRoot `
    -PartitionName $manifestPartitionName `
    -InputFingerprint $manifestFingerprint `
    -RequiredPaths $manifestOutputPaths
Write-Host ("[stage-runtime] {0} manifest resources..." -f $(if ($reuseManifestPartition) { "Reusing" } else { "Rebuilding" }))
if (-not $reuseManifestPartition) {
    $existingManifestMetadata = Get-PartitionMetadata -MetadataRoot $stagingMetadataRoot -PartitionName $manifestPartitionName
    $pathsToClean = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($outputPath in $manifestOutputPaths) {
        $pathsToClean.Add($outputPath) | Out-Null
    }
    if ($existingManifestMetadata -and $existingManifestMetadata.outputPaths) {
        foreach ($outputPath in @($existingManifestMetadata.outputPaths)) {
            $pathsToClean.Add([string]$outputPath) | Out-Null
        }
    }
    foreach ($outputPath in $pathsToClean) {
        Remove-PathIfExists -Path $outputPath -AllowedRoot $stageRootPath
    }
}
foreach ($entry in $manifestEntries) {
    $sourcePath = Join-Path $projectRoot $entry.source
    $destinationPath = Join-Path $appRuntimeRoot $entry.destination
    Copy-StagedEntry -SourcePath $sourcePath `
        -DestinationPath $destinationPath `
        -Category $entry.category `
        -Required ([bool]$entry.required) `
        -OverwritePolicy $entry.overwritePolicy `
        -ProfileTags @($entry.profileTags) `
        -LayerPackage ([string]$entry.layerPackage) `
        -ProjectRoot $projectRoot `
        -StageRoot $stageRootPath `
        -Entries $lockEntries `
        -SkipCopy:$reuseManifestPartition
}
if (-not $reuseManifestPartition) {
    Write-PartitionMetadata `
        -MetadataRoot $stagingMetadataRoot `
        -PartitionName $manifestPartitionName `
        -InputFingerprint $manifestFingerprint `
        -OutputPaths $manifestOutputPaths
}

$pythonVersion = [string]$profileConfig.python.version
if ([string]::IsNullOrWhiteSpace($pythonVersion)) {
    throw "Profile '$Profile' does not declare a Python version."
}

$managedPythonRoot = Join-Path $pythonInstallRoot ("cpython-{0}-windows-x86_64-none" -f $pythonVersion)
$managedPythonExe = Join-Path $managedPythonRoot "python.exe"
if (-not (Test-Path -LiteralPath $managedPythonExe)) {
    Write-Host "[stage-runtime] Installing uv-managed Python $pythonVersion ..."
    $uvPythonInstallArgs = @("python", "install", $pythonVersion, "--managed-python")
    if ($Offline) {
        $uvPythonInstallArgs += "--offline"
    }
    & uv @uvPythonInstallArgs | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "uv python install failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $managedPythonExe)) {
        throw "Failed to resolve uv-managed Python executable for version $pythonVersion at '$managedPythonExe'."
    }
}
else {
    Write-Host "[stage-runtime] Reusing uv-managed Python $pythonVersion ..."
}

$uvLockHash = Get-FileSha256 -Path $uvLockPath
$requirementsLockPath = Join-Path $requirementsCacheRoot ("python-requirements.{0}.{1}.{2}.txt" -f $Profile, $uvLockHash, $pythonRuntimePruneFingerprint)
$nltkPayloadLayoutVersion = "nltk-payload-layout-v2"
$pythonPartitionFingerprint = Get-FingerprintFromStrings -Values @(
    "runtime-python",
    $pythonVersion,
    $uvLockHash,
    $pythonRuntimePruneFingerprint,
    (Get-PathFingerprint -Path $pyprojectPath),
    (Get-PathFingerprint -Path $pythonBlacklistPath)
)
$nltkPayloadFingerprint = Get-FingerprintFromStrings -Values @(
    "nltk-payload",
    $nltkPayloadLayoutVersion,
    (Get-PathFingerprint -Path $cmudictPayloadPath),
    (Get-PathFingerprint -Path $averagedPerceptronTaggerPayloadPath),
    (Get-PathFingerprint -Path $averagedPerceptronTaggerEngPayloadPath)
)
$runtimePythonCacheDir = Join-Path (Join-Path $runtimePythonCacheRoot $pythonVersion) $uvLockHash
$runtimePythonCacheExe = Join-Path $runtimePythonCacheDir "python.exe"

if (-not (Test-Path -LiteralPath $requirementsLockPath)) {
    Write-Host "[stage-runtime] Exporting runtime requirements from uv.lock ..."
    $uvExportArgs = @(
        "export",
        "--project", $projectRoot,
        "--frozen",
        "--no-dev",
        "--no-emit-project",
        "--no-hashes",
        "-o", $requirementsLockPath
    )
    foreach ($packageName in $pythonRuntimePruneEntries) {
        $uvExportArgs += @("--prune", $packageName)
    }
    if ($Offline) {
        $uvExportArgs += "--offline"
    }
    & uv @uvExportArgs | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "uv export failed with exit code $LASTEXITCODE."
    }
}
else {
    Write-Host "[stage-runtime] Reusing exported runtime requirements..."
}

if ($Offline -and (Test-Path -LiteralPath $wheelhouseMetadataPath)) {
    $wheelhouseMetadata = Load-JsonFile -Path $wheelhouseMetadataPath
    if ($wheelhouseMetadata.uvLockSha256 -ne $uvLockHash) {
        throw "Offline wheelhouse cache does not match current uv.lock."
    }
}

$pythonCachePartitionName = "runtime-python-cache"
$reusePythonCachePartition = Test-PartitionReusable `
    -MetadataRoot $stagingMetadataRoot `
    -PartitionName $pythonCachePartitionName `
    -InputFingerprint $pythonPartitionFingerprint `
    -RequiredPaths @($runtimePythonCacheDir, $runtimePythonCacheExe)
Write-Host ("[stage-runtime] {0} cached runtime Python payload..." -f $(if ($reusePythonCachePartition) { "Reusing" } else { "Rebuilding" }))
if (-not $reusePythonCachePartition) {
    $existingPythonCacheMetadata = Get-PartitionMetadata -MetadataRoot $stagingMetadataRoot -PartitionName $pythonCachePartitionName
    $pathsToClean = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    $pathsToClean.Add($runtimePythonCacheDir) | Out-Null
    if ($existingPythonCacheMetadata -and $existingPythonCacheMetadata.outputPaths) {
        foreach ($outputPath in @($existingPythonCacheMetadata.outputPaths)) {
            $pathsToClean.Add([string]$outputPath) | Out-Null
        }
    }
    foreach ($outputPath in $pathsToClean) {
        Remove-PathIfExists -Path $outputPath -AllowedRoot $cacheRoot
    }

    Write-Host "[stage-runtime] Copying base Python runtime into cache..."
    Copy-StagedEntry -SourcePath $managedPythonRoot `
        -DestinationPath $runtimePythonCacheDir `
        -Category "python-runtime-base" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @() `
        -ProjectRoot $managedPythonRoot `
        -StageRoot $runtimePythonCacheDir `
        -Entries $lockEntries `
        -SkipLockEntries
    Remove-BlacklistedPaths -RuntimeRoot $runtimePythonCacheDir -BlacklistEntries $pythonBlacklistEntries

    Write-Host "[stage-runtime] Installing runtime dependencies into cached Python ..."
    $uvInstallArgs = @(
        "pip",
        "install",
        "--project", $projectRoot,
        "--python", $managedPythonExe,
        "--prefix", $runtimePythonCacheDir,
        "--requirements", $requirementsLockPath,
        "--cache-dir", $wheelhouseDir,
        "--index", "https://download.pytorch.org/whl/cu124",
        "--index-strategy", "unsafe-best-match",
        "--python-version", "3.11",
        "--python-platform", "x86_64-pc-windows-msvc",
        "--link-mode", "copy",
        "--strict"
    )
    if ($Offline) {
        $uvInstallArgs += "--offline"
    }
    & uv @uvInstallArgs | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "uv pip install failed with exit code $LASTEXITCODE."
    }

    Write-PartitionMetadata `
        -MetadataRoot $stagingMetadataRoot `
        -PartitionName $pythonCachePartitionName `
        -InputFingerprint $pythonPartitionFingerprint `
        -OutputPaths @($runtimePythonCacheDir)
}

Write-Host "[stage-runtime] Recording installed dependency payload..."
$wheelhouseMetadata = [ordered]@{
    schemaVersion = 1
    pythonVersion = $pythonVersion
    uvLockSha256  = $uvLockHash
    generatedAt   = (Get-Date).ToString("o")
}
Write-Utf8File -Path $wheelhouseMetadataPath -Content ($wheelhouseMetadata | ConvertTo-Json -Depth 10)

$stagePythonPartitionName = "runtime-python-stage"
$stagedPythonExe = Join-Path $runtimePythonDir "python.exe"
$stagePythonPartitionFingerprint = Get-FingerprintFromStrings -Values @(
    $pythonPartitionFingerprint,
    $nltkPayloadFingerprint
)
$reuseStagePythonPartition = Test-PartitionReusable `
    -MetadataRoot $stagingMetadataRoot `
    -PartitionName $stagePythonPartitionName `
    -InputFingerprint $stagePythonPartitionFingerprint `
    -RequiredPaths @($runtimePythonDir, $stagedPythonExe)
Write-Host ("[stage-runtime] {0} staged runtime Python payload..." -f $(if ($reuseStagePythonPartition) { "Reusing" } else { "Rebuilding" }))
if (-not $reuseStagePythonPartition) {
    $existingStagePythonMetadata = Get-PartitionMetadata -MetadataRoot $stagingMetadataRoot -PartitionName $stagePythonPartitionName
    $pathsToClean = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    $pathsToClean.Add($runtimePythonDir) | Out-Null
    if ($existingStagePythonMetadata -and $existingStagePythonMetadata.outputPaths) {
        foreach ($outputPath in @($existingStagePythonMetadata.outputPaths)) {
            $pathsToClean.Add([string]$outputPath) | Out-Null
        }
    }
    foreach ($outputPath in $pathsToClean) {
        Remove-PathIfExists -Path $outputPath -AllowedRoot $stageRootPath
    }

    Copy-StagedEntry -SourcePath $runtimePythonCacheDir `
        -DestinationPath $runtimePythonDir `
        -Category "python-runtime-base" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @() `
        -ProjectRoot $runtimePythonCacheDir `
        -StageRoot $stageRootPath `
        -Entries $lockEntries `
        -SkipLockEntries

    $runtimeNltkDataDir = Join-Path $runtimePythonDir "nltk_data"
    $runtimeNltkCorporaDir = Join-Path $runtimeNltkDataDir "corpora"
    $runtimeNltkTaggersDir = Join-Path $runtimeNltkDataDir "taggers"
    $runtimeNltkCorporaZipPath = Join-Path $runtimeNltkCorporaDir "cmudict.zip"
    $runtimeNltkAveragedPerceptronTaggerZipPath = Join-Path $runtimeNltkTaggersDir "averaged_perceptron_tagger.zip"
    $runtimeNltkAveragedPerceptronTaggerEngZipPath = Join-Path $runtimeNltkTaggersDir "averaged_perceptron_tagger_eng.zip"
    Ensure-Directory -Path $runtimeNltkCorporaDir
    Ensure-Directory -Path $runtimeNltkTaggersDir

    Write-Host "[stage-runtime] Copying bundled NLTK payload zips into staged runtime ..."
    Copy-Item -LiteralPath $cmudictPayloadPath -Destination $runtimeNltkCorporaZipPath -Force
    Copy-Item -LiteralPath $averagedPerceptronTaggerPayloadPath -Destination $runtimeNltkAveragedPerceptronTaggerZipPath -Force
    Copy-Item -LiteralPath $averagedPerceptronTaggerEngPayloadPath -Destination $runtimeNltkAveragedPerceptronTaggerEngZipPath -Force

    Write-Host "[stage-runtime] Extracting bundled NLTK payload into staged runtime ..."
    Expand-Archive -LiteralPath $cmudictPayloadPath -DestinationPath $runtimeNltkCorporaDir -Force
    Expand-Archive -LiteralPath $averagedPerceptronTaggerPayloadPath -DestinationPath $runtimeNltkTaggersDir -Force
    Expand-Archive -LiteralPath $averagedPerceptronTaggerEngPayloadPath -DestinationPath $runtimeNltkTaggersDir -Force

    Write-PartitionMetadata `
        -MetadataRoot $stagingMetadataRoot `
        -PartitionName $stagePythonPartitionName `
        -InputFingerprint $stagePythonPartitionFingerprint `
        -OutputPaths @($runtimePythonDir)
}

$runtimeFiles = Get-ChildItem -LiteralPath $runtimePythonDir -Recurse -File | Where-Object {
    $_.Extension -notin @(".pyc", ".pyo") -and
    $_.FullName -notmatch "\\__pycache__(\\|$)"
}
foreach ($file in $runtimeFiles) {
    $relativePath = Get-RelativePathNormalized -BasePath $runtimePythonDir -TargetPath $file.FullName
    $destinationLabel = Get-RelativePathNormalized -BasePath $stageRootPath -TargetPath $file.FullName
    $category = if ($relativePath.StartsWith("Lib/site-packages/", [System.StringComparison]::OrdinalIgnoreCase)) {
        "python-site-packages"
    }
    else {
        "python-runtime-base"
    }
    Add-LockEntry -Entries $lockEntries `
        -Source ("generated://runtime-python/{0}" -f $relativePath) `
        -Destination $destinationLabel `
        -Category $category `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @() `
        -LayerPackage "runtime"
}

$builtinVoiceFingerprintValues = New-Object System.Collections.Generic.List[string]
$builtinVoiceFingerprintValues.Add((Get-PathFingerprint -Path $profilePath)) | Out-Null
foreach ($voice in $profileConfig.builtinVoices) {
    $gptSourcePath = Join-Path $projectRoot ([string]$voice.gptSource)
    $sovitsSourcePath = Join-Path $projectRoot ([string]$voice.sovitsSource)
    $refAudioSourcePath = Join-Path $projectRoot ([string]$voice.refAudioSource)
    $builtinVoiceFingerprintValues.Add((
            "{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}" -f
            [string]$voice.voiceId,
            [string]$voice.destinationDir,
            [string]$voice.description,
            [string]$voice.refText,
            [string]$voice.refLang,
            (ConvertTo-Json $voice.defaults -Depth 10 -Compress),
            (Get-PathFingerprint -Path $gptSourcePath),
            (Get-PathFingerprint -Path $sovitsSourcePath),
            (Get-PathFingerprint -Path $refAudioSourcePath)
        )) | Out-Null
}
$builtinVoicePartitionName = "builtin-voices"
$builtinVoiceFingerprint = Get-TextSha256 -Text (($builtinVoiceFingerprintValues -join "`n"))
$voiceDestinationRootSet = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($voice in $profileConfig.builtinVoices) {
    $voiceDestinationRootSet.Add((Join-Path $appRuntimeRoot ([string]$voice.destinationDir))) | Out-Null
}
$voiceDestinationRoots = @($voiceDestinationRootSet)
$voicesConfigPath = Join-Path $configDir "voices.json"
$builtinVoiceRequiredPaths = @($voiceDestinationRoots + $voicesConfigPath)
$reuseBuiltinVoicePartition = Test-PartitionReusable `
    -MetadataRoot $stagingMetadataRoot `
    -PartitionName $builtinVoicePartitionName `
    -InputFingerprint $builtinVoiceFingerprint `
    -RequiredPaths $builtinVoiceRequiredPaths
Write-Host ("[stage-runtime] {0} builtin voice profile..." -f $(if ($reuseBuiltinVoicePartition) { "Reusing" } else { "Rebuilding" }))
if (-not $reuseBuiltinVoicePartition) {
    $existingBuiltinVoiceMetadata = Get-PartitionMetadata -MetadataRoot $stagingMetadataRoot -PartitionName $builtinVoicePartitionName
    $pathsToClean = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($outputPath in $voiceDestinationRoots) {
        $pathsToClean.Add($outputPath) | Out-Null
    }
    if ($existingBuiltinVoiceMetadata -and $existingBuiltinVoiceMetadata.outputPaths) {
        foreach ($outputPath in @($existingBuiltinVoiceMetadata.outputPaths)) {
            $pathsToClean.Add([string]$outputPath) | Out-Null
        }
    }
    foreach ($outputPath in $pathsToClean) {
        Remove-PathIfExists -Path $outputPath -AllowedRoot $stageRootPath
    }
    Ensure-Directory -Path $builtinModelDir
}

$builtinVoices = [ordered]@{}
foreach ($voice in $profileConfig.builtinVoices) {
    $voiceId = [string]$voice.voiceId
    if ([string]::IsNullOrWhiteSpace($voiceId)) {
        throw "Builtin voice entry is missing voiceId."
    }
    $voiceLayerPackage = if ([string]::IsNullOrWhiteSpace([string]$voice.layerPackage)) { "models" } else { [string]$voice.layerPackage }

    $voiceDestinationDir = Join-Path $appRuntimeRoot ([string]$voice.destinationDir)
    Ensure-Directory -Path $voiceDestinationDir

    $gptSourcePath = Join-Path $projectRoot ([string]$voice.gptSource)
    $sovitsSourcePath = Join-Path $projectRoot ([string]$voice.sovitsSource)
    $refAudioSourcePath = Join-Path $projectRoot ([string]$voice.refAudioSource)
    $gptDestinationPath = Join-Path $voiceDestinationDir (Split-Path -Leaf $gptSourcePath)
    $sovitsDestinationPath = Join-Path $voiceDestinationDir (Split-Path -Leaf $sovitsSourcePath)
    $refAudioDestinationPath = Join-Path $voiceDestinationDir (Split-Path -Leaf $refAudioSourcePath)

    Copy-StagedEntry -SourcePath $gptSourcePath `
        -DestinationPath $gptDestinationPath `
        -Category "builtin-voice" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @($Profile) `
        -LayerPackage $voiceLayerPackage `
        -ProjectRoot $projectRoot `
        -StageRoot $stageRootPath `
        -Entries $lockEntries `
        -SkipCopy:$reuseBuiltinVoicePartition
    Copy-StagedEntry -SourcePath $sovitsSourcePath `
        -DestinationPath $sovitsDestinationPath `
        -Category "builtin-voice" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @($Profile) `
        -LayerPackage $voiceLayerPackage `
        -ProjectRoot $projectRoot `
        -StageRoot $stageRootPath `
        -Entries $lockEntries `
        -SkipCopy:$reuseBuiltinVoicePartition
    Copy-StagedEntry -SourcePath $refAudioSourcePath `
        -DestinationPath $refAudioDestinationPath `
        -Category "builtin-voice" `
        -Required $true `
        -OverwritePolicy "replace" `
        -ProfileTags @($Profile) `
        -LayerPackage $voiceLayerPackage `
        -ProjectRoot $projectRoot `
        -StageRoot $stageRootPath `
        -Entries $lockEntries `
        -SkipCopy:$reuseBuiltinVoicePartition

    $builtinVoices[$voiceId] = [ordered]@{
        gpt_path    = Get-RelativePathNormalized -BasePath $appRuntimeRoot -TargetPath $gptDestinationPath
        sovits_path = Get-RelativePathNormalized -BasePath $appRuntimeRoot -TargetPath $sovitsDestinationPath
        ref_audio   = Get-RelativePathNormalized -BasePath $appRuntimeRoot -TargetPath $refAudioDestinationPath
        ref_text    = [string]$voice.refText
        ref_lang    = [string]$voice.refLang
        description = [string]$voice.description
        defaults    = [ordered]@{
            speed        = [double]$voice.defaults.speed
            top_k        = [int]$voice.defaults.top_k
            top_p        = [double]$voice.defaults.top_p
            temperature  = [double]$voice.defaults.temperature
            pause_length = [double]$voice.defaults.pause_length
        }
        managed     = $false
        created_at  = $null
        updated_at  = $null
    }
}

if (-not $reuseBuiltinVoicePartition) {
    Write-Utf8File -Path $voicesConfigPath -Content ($builtinVoices | ConvertTo-Json -Depth 20)
    Write-PartitionMetadata `
        -MetadataRoot $stagingMetadataRoot `
        -PartitionName $builtinVoicePartitionName `
        -InputFingerprint $builtinVoiceFingerprint `
        -OutputPaths @($voiceDestinationRoots + $voicesConfigPath)
}
Add-LockEntry -Entries $lockEntries `
    -Source "generated://config/voices.json" `
    -Destination (Get-RelativePathNormalized -BasePath $stageRootPath -TargetPath $voicesConfigPath) `
    -Category "config" `
    -Required $true `
    -OverwritePolicy "replace" `
    -ProfileTags @($Profile) `
    -LayerPackage "app-core"

$manifestLock = [ordered]@{
    schemaVersion = 1
    buildVersion  = [string]$desktopPackage.version
    profile       = [string]$profileConfig.profileId
    flavor        = [string]$flavorConfig.flavorId
    generatedAt   = (Get-Date).ToString("o")
    entries       = $lockEntries
}
Write-Utf8File -Path $manifestLockPath -Content ($manifestLock | ConvertTo-Json -Depth 20)

Write-Host "[stage-runtime] Runtime staging completed:"
Write-Host "  - $frontendStagePath"
Write-Host "  - $backendStagePath"
Write-Host "  - $gptSovitsStagePath"
Write-Host "  - $runtimePythonDir"
Write-Host "  - $builtinModelDir"
Write-Host "  - $configDir"
Write-Host "  - $wheelhouseDir"
Write-Host "  - $manifestLockPath"
