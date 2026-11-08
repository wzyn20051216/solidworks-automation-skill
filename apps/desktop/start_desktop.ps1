<# 
.SYNOPSIS
CAD otomasyonu teslimat çalışma tezgâhı masaüstü prototipini başlatır.

.DESCRIPTION
Betik depo kök dizininde çalışır; önce PySide6 kontrol edilir, eksikse kurulum komutu gösterilir, ardından PySide6 masaüstü uygulaması başlatılır.
#>

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DesktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $DesktopDir "..\..")
Set-Location $RepoRoot

$HasPySide = python -c "import importlib.util; print('1' if importlib.util.find_spec('PySide6') else '0')"
if ($HasPySide.Trim() -ne "1") {
    Write-Host "PySide6 eksik; once sunu calistirin:" -ForegroundColor Yellow
    Write-Host "python -m pip install -r apps\desktop\requirements.txt" -ForegroundColor Cyan
    exit 1
}

python apps\desktop\run.py
