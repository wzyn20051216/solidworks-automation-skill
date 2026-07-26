$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $repoRoot "release-output\nsis-test"
$version = (Get-Content -LiteralPath (Join-Path $repoRoot "apps\workbench-ui\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
$installer = Join-Path $repoRoot "release-output\CAD-Studio-$version-Setup-x64.exe"

if (Test-Path -LiteralPath $installRoot) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
}
$install = Start-Process -FilePath $installer -ArgumentList "/S", "/D=$installRoot" -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "Installer exit code: $($install.ExitCode)" }

$required = @(
    "cad-studio.exe",
    "skill\SKILL.md",
    "skill\apps\desktop\cad_workbench\queue_worker.py",
    "skill\mcp-server\server.py",
    "skill\examples\08_mini_fan_motion_assembly.py",
    "skill\subskills\autocad-automation\SKILL.md",
    "uninstall.exe"
)
$result = $required | ForEach-Object {
    [pscustomobject]@{ Path = $_; Exists = Test-Path -LiteralPath (Join-Path $installRoot $_) }
}
$result | Format-Table -AutoSize
if ($result.Exists -contains $false) { throw "Installed resources are incomplete." }

$uninstall = Start-Process -FilePath (Join-Path $installRoot "uninstall.exe") -ArgumentList "/S" -Wait -PassThru
if ($uninstall.ExitCode -ne 0) { throw "Uninstaller exit code: $($uninstall.ExitCode)" }
Start-Sleep -Seconds 2
[pscustomobject]@{
    InstallerExit = $install.ExitCode
    UninstallerExit = $uninstall.ExitCode
    InstallDirRemaining = Test-Path -LiteralPath $installRoot
}
