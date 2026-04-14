param(
    [ValidateSet("default")]
    [string]$Profile = "default",

    [ValidateSet("portable", "installed")]
    [string]$Distribution = "portable",

    [switch]$SkipPortableZip,

    [string]$InnoSetupCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",

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

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopRoot = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $desktopRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$desktopPackageJsonPath = Join-Path $desktopRoot "package.json"
$desktopPackage = Load-JsonFile -Path $desktopPackageJsonPath
$packageVersion = [string]$desktopPackage.version
if ([string]::IsNullOrWhiteSpace($packageVersion)) {
    throw "desktop/package.json version is required for versioned release outputs."
}
$releaseRoot = Join-Path $desktopRoot "release"
$releaseVersionRoot = Join-Path $releaseRoot $packageVersion
$stageRuntimeScript = Join-Path $scriptDir "stage-runtime.ps1"
$assemblePortableScript = Join-Path $scriptDir "assemble-portable.ps1"
$innoSetupScript = Join-Path $desktopRoot "packaging\installers\windows-installer.iss"
$setupIconPath = Join-Path $projectRoot "frontend\public\512.ico"
$winUnpackedRoot = Join-Path $releaseVersionRoot "win-unpacked"
$winUnpackedExe = Join-Path $winUnpackedRoot "NeoTTS.exe"
$installerBaseName = "NeoTTS-Setup-$packageVersion"
$portableZipDefaultPath = Join-Path $releaseVersionRoot "NeoTTS-Portable-$packageVersion.zip"
$cacheRoot = Join-Path $desktopRoot ".cache"
$buildMetadataRoot = Join-Path $cacheRoot "build-metadata"
$frontendDistRoot = Join-Path $frontendRoot "dist"
$desktopDistRoot = Join-Path $desktopRoot "dist"
$desktopSourceRoot = Join-Path $desktopRoot "src"

foreach ($requiredPath in @($frontendRoot, $stageRuntimeScript, $desktopPackageJsonPath)) {
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

Write-Host "[build-integrated-package] Cleaning current version release outputs..."
Remove-DirectoryIfExists -Path $releaseVersionRoot -AllowedRoot $releaseRoot

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
    "-Flavor", $Distribution
)
if ($Offline) {
    $stageRuntimeArgs += "-Offline"
}
Invoke-NativeStep -Label "Stage runtime" `
    -WorkingDirectory $desktopRoot `
    -FilePath "powershell.exe" `
    -Arguments $stageRuntimeArgs

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

foreach ($requiredPath in @($winUnpackedRoot, $winUnpackedExe)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        if ($builderFailed) {
            throw $builderFailure
        }
        throw "Integrated package validation failed after builder: missing $requiredPath"
    }
}

if ($Distribution -eq "portable") {
    $portableLabel = if ($SkipPortableZip) { "Assemble portable root (skip zip)" } else { "Assemble portable zip" }
    $assemblePortableArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $assemblePortableScript,
        "-ReleaseRoot", $releaseVersionRoot,
        "-PortableZipPath", $portableZipDefaultPath
    )
    if ($SkipPortableZip) {
        $assemblePortableArgs += "-SkipZip"
    }
    Invoke-NativeStep -Label $portableLabel `
        -WorkingDirectory $desktopRoot `
        -FilePath "powershell.exe" `
        -Arguments $assemblePortableArgs

    $portableRootPath = Join-Path $releaseVersionRoot "NeoTTS-Portable"
    if ($SkipPortableZip) {
        foreach ($requiredPath in @($winUnpackedExe, $portableRootPath, (Join-Path $portableRootPath "NeoTTS.exe"), (Join-Path $portableRootPath "portable.flag"))) {
            if (-not (Test-Path -LiteralPath $requiredPath)) {
                throw "Portable package validation failed: missing $requiredPath"
            }
        }
        Write-Host "[build-integrated-package] Artifacts ready:"
        Write-Host "  - portable root: $portableRootPath"
        Write-Host "  - win-unpacked:  $winUnpackedExe"
        Write-Host "  - release root:  $releaseVersionRoot"
        Write-Host "  - note:          zip packaging was skipped"
    }
    else {
        $portableZipPath = Find-SingleArtifact -ReleaseRoot $releaseVersionRoot -Filter "*Portable*.zip" -Label "portable zip"
        foreach ($requiredPath in @($winUnpackedExe, $portableZipPath)) {
            if (-not (Test-Path -LiteralPath $requiredPath)) {
                throw "Portable package validation failed: missing $requiredPath"
            }
        }

        Write-Host "[build-integrated-package] Artifacts ready:"
        Write-Host "  - portable zip: $portableZipPath"
        Write-Host "  - win-unpacked: $winUnpackedExe"
        Write-Host "  - release root: $releaseVersionRoot"
        Write-Host "  - installer:    run 'npm run package:installed' when needed"
    }
}
else {
    Invoke-NativeStep -Label "Build Windows installer with Inno Setup" `
        -WorkingDirectory $desktopRoot `
        -FilePath $InnoSetupCompiler `
        -Arguments @(
            "/Qp",
            "/DAppId=com.neo-tts.desktop",
            "/DAppName=NeoTTS",
            "/DAppVersion=$packageVersion",
            "/DAppExeName=NeoTTS.exe",
            "/DSourceRoot=$winUnpackedRoot",
            "/DOutputDir=$releaseVersionRoot",
            "/DOutputBaseFilename=$installerBaseName",
            "/DSetupIconFile=$setupIconPath",
            $innoSetupScript
        )

    $installerPath = Find-SingleArtifact -ReleaseRoot $releaseVersionRoot -Filter "*Setup*.exe" -Label "Windows installer" -ExcludePattern "__uninstaller"
    foreach ($requiredPath in @($winUnpackedExe, $installerPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Installed package validation failed after Inno Setup: missing $requiredPath"
        }
    }

    Write-Host "[build-integrated-package] Artifacts ready:"
    Write-Host "  - installer:    $installerPath"
    Write-Host "  - win-unpacked: $winUnpackedExe"
    Write-Host "  - release root: $releaseVersionRoot"
    Write-Host "  - portable zip: run 'npm run package' when needed"
}
