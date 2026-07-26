param(
    [string]$Version = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$uiRoot = Join-Path $repoRoot "apps\workbench-ui"
$tauriRoot = Join-Path $uiRoot "src-tauri"
$releaseRoot = Join-Path $repoRoot "release-output"
$tauriConfig = Get-Content -LiteralPath (Join-Path $tauriRoot "tauri.conf.json") -Raw | ConvertFrom-Json
$packageConfig = Get-Content -LiteralPath (Join-Path $uiRoot "package.json") -Raw | ConvertFrom-Json
$cargoManifest = Get-Content -LiteralPath (Join-Path $tauriRoot "Cargo.toml") -Raw
$configuredVersion = [string]$tauriConfig.version
$cargoVersionMatch = [regex]::Match($cargoManifest, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $cargoVersionMatch.Success) { throw "Cannot read Cargo package version." }
$cargoVersion = $cargoVersionMatch.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = $configuredVersion }
if ($Version -ne $configuredVersion -or $Version -ne [string]$packageConfig.version -or $Version -ne $cargoVersion) {
    throw "Version mismatch: requested=$Version, tauri=$configuredVersion, npm=$($packageConfig.version), cargo=$cargoVersion"
}
$portableName = "CAD-Studio-$Version-Windows-x64"
$portableRoot = Join-Path $releaseRoot $portableName

if (-not $SkipBuild) {
    Push-Location $uiRoot
    try {
        npm run desktop:bundle
        if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
    }
    finally {
        Pop-Location
    }
}

$binary = Join-Path $tauriRoot "target\release\cad-studio.exe"
$skill = Join-Path $tauriRoot "resources\skill"
$installer = Get-Item -LiteralPath (Join-Path $tauriRoot "target\release\bundle\nsis\CAD Studio_${Version}_x64-setup.exe") -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $binary)) { throw "Missing release binary: $binary" }
if (-not (Test-Path -LiteralPath (Join-Path $skill "SKILL.md"))) { throw "Missing bundled skill: $skill" }
foreach ($required in @(
    "apps\desktop\cad_workbench\queue_worker.py",
    "apps\desktop\cad_workbench\schemas\automation_job.schema.json",
    "examples\08_mini_fan_motion_assembly.py",
    "mcp-server\server.py",
    "mcp-server\register_all_ai_mcp.ps1",
    "subskills\autocad-automation\SKILL.md"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $skill $required))) { throw "Bundled skill is incomplete: $required" }
}
if (-not $installer) { throw "NSIS installer was not found." }

if (Test-Path -LiteralPath $releaseRoot) {
    Remove-Item -LiteralPath $releaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null

Copy-Item -LiteralPath $binary -Destination (Join-Path $portableRoot "CAD Studio.exe")
Copy-Item -LiteralPath $skill -Destination (Join-Path $portableRoot "skill") -Recurse
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination $portableRoot
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\CAD_STUDIO_USER_MANUAL.md") -Destination (Join-Path $portableRoot "USER_MANUAL.zh-CN.md")

$portableZip = Join-Path $releaseRoot "$portableName-Portable.zip"
Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $portableZip -CompressionLevel Optimal
$setupPath = Join-Path $releaseRoot "CAD-Studio-$Version-Setup-x64.exe"
Copy-Item -LiteralPath $installer.FullName -Destination $setupPath

$checksums = @($setupPath, $portableZip) | ForEach-Object {
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "$($hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
}
$checksums | Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS.txt") -Encoding ascii

Write-Host "Release files generated: $releaseRoot"
Get-ChildItem -LiteralPath $releaseRoot -File | Select-Object Name, Length
