<#
.SYNOPSIS
将 CAD 自动化交付工作台桌面原型打包为 Windows exe。

.DESCRIPTION
使用 PyInstaller 生成本地可执行文件。输出目录为 apps\desktop\dist\CADAutomationWorkbench。
#>

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DesktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $DesktopDir "..\..")
Set-Location $RepoRoot

$HasPyInstaller = python -c "import importlib.util; print('1' if importlib.util.find_spec('PyInstaller') else '0')"
if ($HasPyInstaller.Trim() -ne "1") {
    Write-Host "正在安装 PyInstaller..." -ForegroundColor Cyan
    python -m pip install pyinstaller
}

python -m PyInstaller `
    --noconfirm `
    --windowed `
    --name CADAutomationWorkbench `
    --distpath apps\desktop\dist `
    --workpath apps\desktop\build `
    --specpath apps\desktop\build `
    apps\desktop\run.py

Write-Host "打包完成: apps\desktop\dist\CADAutomationWorkbench\CADAutomationWorkbench.exe" -ForegroundColor Green
