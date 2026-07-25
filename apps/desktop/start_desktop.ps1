<# 
.SYNOPSIS
启动 CAD 自动化交付工作台桌面原型。

.DESCRIPTION
脚本会在仓库根目录执行，先检查 PySide6，缺失时提示安装命令，再启动 PySide6 桌面应用。
#>

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DesktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $DesktopDir "..\..")
Set-Location $RepoRoot

$HasPySide = python -c "import importlib.util; print('1' if importlib.util.find_spec('PySide6') else '0')"
if ($HasPySide.Trim() -ne "1") {
    Write-Host "缺少 PySide6，请先执行:" -ForegroundColor Yellow
    Write-Host "python -m pip install -r apps\desktop\requirements.txt" -ForegroundColor Cyan
    exit 1
}

python apps\desktop\run.py
