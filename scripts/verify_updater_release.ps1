param(
    [string]$ReleaseRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $repoRoot "release-output"
}
$resolvedReleaseRoot = [System.IO.Path]::GetFullPath($ReleaseRoot)
$expectedReleaseRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "release-output"))
if ($resolvedReleaseRoot -ne $expectedReleaseRoot) {
    throw "Unsafe updater verification path: $resolvedReleaseRoot"
}

$tauriRoot = Join-Path $repoRoot "apps\workbench-ui\src-tauri"
$tauriConfigPath = Join-Path $tauriRoot "tauri.conf.json"
$tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
$version = [string]$tauriConfig.version
$latestPath = Join-Path $resolvedReleaseRoot "latest.json"
$latest = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json
if ([string]$latest.version -ne $version) {
    throw "Updater manifest version mismatch: manifest=$($latest.version), app=$version"
}

$platform = $latest.platforms."windows-x86_64"
if (-not $platform) { throw "latest.json is missing windows-x86_64." }
$expectedUrl = "https://github.com/wzyn20051216/solidworks-automation-skill/releases/download/v$version/CAD-Studio-$version-Setup-x64.exe"
if ([string]$platform.url -ne $expectedUrl) {
    throw "Updater URL mismatch: $($platform.url)"
}

$setupPath = Join-Path $resolvedReleaseRoot "CAD-Studio-$version-Setup-x64.exe"
$signaturePath = "$setupPath.sig"
foreach ($requiredPath in @($setupPath, $signaturePath, (Join-Path $resolvedReleaseRoot "SHA256SUMS.txt"))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Missing updater release artifact: $requiredPath"
    }
}
$signature = (Get-Content -LiteralPath $signaturePath -Raw).Trim()
if ([string]$platform.signature -ne $signature) {
    throw "latest.json signature does not match the published .sig file."
}

$publicKeyPath = Join-Path $env:TEMP "cad-studio-updater-public-$PID.key"
$decodedSignaturePath = Join-Path $env:TEMP "cad-studio-updater-signature-$PID.sig"
try {
    $publicKeyBytes = [Convert]::FromBase64String([string]$tauriConfig.plugins.updater.pubkey)
    [System.IO.File]::WriteAllBytes($publicKeyPath, $publicKeyBytes)
    $signatureBytes = [Convert]::FromBase64String($signature)
    [System.IO.File]::WriteAllBytes($decodedSignaturePath, $signatureBytes)
    cargo run --quiet --manifest-path (Join-Path $tauriRoot "Cargo.toml") --example verify_updater_signature -- $publicKeyPath $setupPath $decodedSignaturePath
    if ($LASTEXITCODE -ne 0) { throw "Updater signature verification failed." }
}
finally {
    if (Test-Path -LiteralPath $publicKeyPath) { Remove-Item -LiteralPath $publicKeyPath -Force }
    if (Test-Path -LiteralPath $decodedSignaturePath) { Remove-Item -LiteralPath $decodedSignaturePath -Force }
}

$checksumLines = Get-Content -LiteralPath (Join-Path $resolvedReleaseRoot "SHA256SUMS.txt")
foreach ($artifact in Get-ChildItem -LiteralPath $resolvedReleaseRoot -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" }) {
    $expectedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash.ToLowerInvariant()
    if (-not ($checksumLines -contains "$expectedHash  $($artifact.Name)")) {
        throw "SHA256SUMS.txt does not cover $($artifact.Name)."
    }
}

Write-Host "Updater release contract verified for CAD Studio $version."
