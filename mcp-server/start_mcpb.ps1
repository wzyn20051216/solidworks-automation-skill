# MCP stdout is reserved for JSON-RPC. Startup diagnostics go to stderr.
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $uv -and $env:USERPROFILE) {
    $standalone = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $standalone -PathType Leaf) { $uv = $standalone }
}
if (-not $uv) {
    [Console]::Error.WriteLine('CAD Studio MCPB requires uv. Install it in a terminal: winget install --id astral-sh.uv -e')
    [Console]::Error.WriteLine('Other installation methods: https://docs.astral.sh/uv/getting-started/installation/')
    [Console]::Error.WriteLine('After installing, exit and reopen your MCP client, then enable this extension again.')
    exit 127
}

$bundleRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
# Resolve from the bundle even when the host starts it in a different directory.
& $uv run --locked --project $bundleRoot --directory $bundleRoot --python 3.12 python -u (Join-Path $PSScriptRoot 'server.py')
exit $LASTEXITCODE
