<#
.SYNOPSIS
CAD otomasyonu teslimat çalışma tezgâhı masaüstü prototipini Windows exe olarak paketler.

.DESCRIPTION
PyInstaller ile yerel yürütülebilir dosya üretir. Çıktı dizini: apps\desktop\dist\CADAutomationWorkbench.
#>

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DesktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $DesktopDir "..\..")
Set-Location $RepoRoot

$HasPyInstaller = python -c "import importlib.util; print('1' if importlib.util.find_spec('PyInstaller') else '0')"
if ($HasPyInstaller.Trim() -ne "1") {
    Write-Host "PyInstaller kuruluyor..." -ForegroundColor Cyan
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

Write-Host "Paketleme tamamlandi: apps\desktop\dist\CADAutomationWorkbench\CADAutomationWorkbench.exe" -ForegroundColor Green
