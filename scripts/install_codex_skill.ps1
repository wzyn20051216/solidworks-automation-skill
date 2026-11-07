param(
    [string]$Target = (Join-Path $env:USERPROFILE ".codex\skills\solidworks-automation")
)

$ErrorActionPreference = "Stop"

$Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SourceSkill = Join-Path $Source "SKILL.md"
if (-not (Test-Path -LiteralPath $SourceSkill)) {
    throw "SKILL.md not found in source checkout: $Source"
}

$Target = [System.IO.Path]::GetFullPath($Target)
$Parent = Split-Path -Parent $Target

if (Test-Path -LiteralPath $Target) {
    $Item = Get-Item -LiteralPath $Target -Force
    if ($Item.LinkType -eq "Junction") {
        $ExistingTarget = @($Item.Target)[0]
        $ExistingTarget = [System.IO.Path]::GetFullPath($ExistingTarget).TrimEnd("\")
        $ExpectedTarget = [System.IO.Path]::GetFullPath($Source).TrimEnd("\")
        if ($ExistingTarget -eq $ExpectedTarget) {
            Write-Host "Codex skill link already points to: $Source"
            exit 0
        }
    }
    throw "Target already exists and will not be modified: $Target"
}

New-Item -ItemType Directory -Path $Parent -Force | Out-Null
New-Item -ItemType Junction -Path $Target -Target $Source | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $Target "SKILL.md"))) {
    throw "Codex skill link validation failed: $Target"
}

Write-Host "Codex skill linked: $Target -> $Source"
