param(
    [string]$Version = "",
    [string]$OutputDirectory = "release-output"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$packageConfig = Get-Content -LiteralPath (Join-Path $repoRoot "package.json") -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = [string]$packageConfig.version }
if ($Version -ne [string]$packageConfig.version) {
    throw "Version mismatch: requested=$Version, package=$($packageConfig.version)"
}

$outputCandidate = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $repoRoot $OutputDirectory
}
$outputRoot = [System.IO.Path]::GetFullPath($outputCandidate)
$repoPath = [System.IO.Path]::GetFullPath($repoRoot)
if (-not $outputRoot.StartsWith($repoPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe MCPB output path: $outputRoot"
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$standard = Join-Path $outputRoot "SolidWorks-Automation-Skill-$Version.mcpb"
$smithery = Join-Path $outputRoot "SolidWorks-Automation-Skill-$Version-smithery.mcpb"
foreach ($target in @($standard, $smithery)) {
    if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite existing MCPB: $target" }
}

$mcpbPackage = "@anthropic-ai/mcpb@2.1.2"
& npx --yes $mcpbPackage pack $repoRoot $standard
if ($LASTEXITCODE -ne 0) { throw "MCPB pack failed." }
& python (Join-Path $PSScriptRoot "verify_mcpb.py") $standard --version $Version
if ($LASTEXITCODE -ne 0) { throw "MCPB runtime verification failed." }

& python (Join-Path $PSScriptRoot "build_smithery_mcpb.py") `
    $standard $smithery --mode search --repo-root $repoRoot
if ($LASTEXITCODE -ne 0) { throw "Smithery MCPB build failed." }
& python (Join-Path $PSScriptRoot "verify_mcpb.py") $smithery --version $Version
if ($LASTEXITCODE -ne 0) { throw "Smithery MCPB runtime verification failed." }

Write-Output "MCPB files generated:"
Get-Item -LiteralPath $standard, $smithery | Select-Object Name, Length
