param(
    [string]$Version = "",
    [string]$OutputDirectory = "release-output"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$packageConfig = Get-Content -LiteralPath (Join-Path $repoRoot "package.json") -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = [string]$packageConfig.version }
if ($Version -ne [string]$packageConfig.version) {
    throw "Core version mismatch: requested=$Version, package=$($packageConfig.version)"
}

$outputCandidate = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $repoRoot $OutputDirectory
}
$outputRoot = [System.IO.Path]::GetFullPath($outputCandidate)
$repoPath = [System.IO.Path]::GetFullPath($repoRoot)
if (-not $outputRoot.StartsWith($repoPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe core release output path: $outputRoot"
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

& python (Join-Path $PSScriptRoot "release_check.py") --core-only
if ($LASTEXITCODE -ne 0) { throw "Core release metadata validation failed." }

$skillZip = Join-Path $outputRoot "SolidWorks-Automation-Skill-$Version.zip"
if (Test-Path -LiteralPath $skillZip) {
    throw "Refusing to overwrite existing Skill archive: $skillZip"
}
& python (Join-Path $PSScriptRoot "build_skill_release.py") --version $Version --output $skillZip
if ($LASTEXITCODE -ne 0) { throw "Skill archive build failed." }

& powershell -NoProfile -File (Join-Path $PSScriptRoot "build_mcpb.ps1") `
    -Version $Version -OutputDirectory $outputRoot
if ($LASTEXITCODE -ne 0) { throw "MCP bundle build failed." }

$assets = @(
    $skillZip,
    (Join-Path $outputRoot "SolidWorks-Automation-Skill-$Version.mcpb"),
    (Join-Path $outputRoot "SolidWorks-Automation-Skill-$Version-smithery.mcpb")
)
$checksumPath = Join-Path $outputRoot "SHA256SUMS.txt"
$checksumLines = foreach ($asset in $assets) {
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
        throw "Missing core release artifact: $asset"
    }
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $asset
    "$($hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($asset))"
}
$checksumLines | Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Output "Core Skill + MCP release generated: $outputRoot"
Get-Item -LiteralPath ($assets + $checksumPath) | Select-Object Name, Length
