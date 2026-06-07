<#
.SYNOPSIS
Register the SolidWorks MCP Server for common local AI clients.

.DESCRIPTION
This wrapper calls register_all_ai_mcp.js and configures Codex, Claude Code,
Claude Desktop, Cursor, and Windsurf where possible.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies
#>

param(
    [string]$Name = "solidworks",
    [string]$Python = "python",
    [string]$Clients = "all",
    [switch]$InstallDependencies,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "register_all_ai_mcp.js"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "register_all_ai_mcp.js not found: $scriptPath"
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "node command not found. Install Node.js or run the npx installer."
}

$arguments = @(
    $scriptPath,
    "--name", $Name,
    "--python", $Python,
    "--clients", $Clients
)

if ($InstallDependencies) {
    $arguments += "--install-dependencies"
}

if ($Strict) {
    $arguments += "--strict"
}

& node @arguments
exit $LASTEXITCODE
