<#
.SYNOPSIS
Register the SolidWorks MCP Server for Codex.

.DESCRIPTION
This script changes Codex MCP configuration only when users run it explicitly.
It validates server.py, optionally installs Python dependencies, and registers
the local stdio MCP Server through `codex mcp add`.

.PARAMETER Name
MCP Server name. Default: solidworks.

.PARAMETER Python
Python command or full executable path used to launch the MCP Server.
Default: python.

.PARAMETER InstallDependencies
Install Python dependencies from mcp-server/requirements.txt before registering.

.PARAMETER Force
Remove and re-register the MCP Server when the same name already exists.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_codex_mcp.ps1 -InstallDependencies
#>

param(
    [string]$Name = "solidworks",
    [string]$Python = "python",
    [switch]$InstallDependencies,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

$serverPath = Join-Path $PSScriptRoot "server.py"
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $serverPath)) {
    throw "MCP server not found: $serverPath"
}

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "codex command not found. Install Codex CLI or add server.py manually in your MCP client."
}

Write-Host "SolidWorks MCP Server: $serverPath"

if ($InstallDependencies) {
    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        throw "Requirements file not found: $requirementsPath"
    }
    Write-Host "Installing MCP Server dependencies..."
    Invoke-CheckedCommand $Python -m pip install -r $requirementsPath
}

Write-Host "Checking Python syntax..."
Invoke-CheckedCommand $Python -m py_compile $serverPath

$probePreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "SilentlyContinue"
    $null = & codex mcp get $Name 2>$null
    $exists = ($LASTEXITCODE -eq 0)
}
finally {
    $ErrorActionPreference = $probePreference
}

if ($exists) {
    if (-not $Force) {
        Write-Host "MCP Server already exists in Codex: $Name"
        Write-Host "Use -Force to overwrite it. Current config:"
        & codex mcp get $Name
        exit 0
    }

    Write-Host "Removing existing MCP Server: $Name"
    Invoke-CheckedCommand codex mcp remove $Name
}

Write-Host "Registering Codex MCP Server: $Name"
Invoke-CheckedCommand codex mcp add $Name -- $Python $serverPath

Write-Host "Registration complete. Current config:"
Invoke-CheckedCommand codex mcp get $Name
