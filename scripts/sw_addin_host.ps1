<#
.SYNOPSIS
Build, register, probe, or unregister the CAD Studio SolidWorks C# Add-in host.

.DESCRIPTION
CurrentUser mode avoids elevation. Machine mode uses 64-bit RegAsm and HKLM.
All registry writes are scoped to the fixed Add-in GUID.
#>
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Register', 'ComSmoke', 'Probe', 'Unregister')]
    [string]$Action = 'Build',

    [ValidateSet('CurrentUser', 'Machine')]
    [string]$RegistrationScope = 'CurrentUser',

    [string]$SolidWorksApiDir = $env:SOLIDWORKS_API_DIR,
    [string]$DotNetPath = "$env:LOCALAPPDATA\Microsoft\dotnet\dotnet.exe",
    [string]$Configuration = 'Release',
    [switch]$ElevatedChild
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectPath = Join-Path $ProjectRoot 'dotnet\CadStudio.SolidWorks.AddinHost\CadStudio.SolidWorks.AddinHost.csproj'
$OutputDir = Join-Path $ProjectRoot "dotnet\CadStudio.SolidWorks.AddinHost\bin\$Configuration\net48"
$AssemblyPath = Join-Path $OutputDir 'CadStudio.SolidWorks.AddinHost.dll'
$AddinGuid = '{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}'
$ProgId = 'CadStudio.SolidWorks.AddinHost'
$ClassName = 'CadStudio.SolidWorks.AddinHost.SwAddin'
$RegAsmPath = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"

function Resolve-SolidWorksApiDir {
    if ($SolidWorksApiDir -and (Test-Path (Join-Path $SolidWorksApiDir 'SolidWorks.Interop.sldworks.dll'))) {
        return (Resolve-Path $SolidWorksApiDir).Path
    }
    $setupKeys = Get-ChildItem 'HKLM:\SOFTWARE\SOLIDWORKS' -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -like 'SOLIDWORKS 20*' } |
        Sort-Object PSChildName -Descending
    foreach ($setupKey in $setupKeys) {
        $setup = Get-ItemProperty (Join-Path $setupKey.PSPath 'Setup') -ErrorAction SilentlyContinue
        $installFolder = $setup.'SolidWorks Folder'
        if ($installFolder) {
            $candidate = Join-Path $installFolder 'api\redist'
            if (Test-Path (Join-Path $candidate 'SolidWorks.Interop.sldworks.dll')) {
                return (Resolve-Path $candidate).Path
            }
        }
    }
    throw 'SolidWorks PIA not found. Pass -SolidWorksApiDir <SOLIDWORKS\api\redist>.'
}

function Build-AddinHost {
    $apiDir = Resolve-SolidWorksApiDir
    if (-not (Test-Path $DotNetPath)) {
        throw "dotnet SDK not found: $DotNetPath"
    }
    & $DotNetPath build $ProjectPath -c $Configuration "-p:SolidWorksApiDir=$apiDir" --nologo
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $AssemblyPath)) {
        throw "Add-in build failed: $AssemblyPath"
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedSelf {
    param([ValidateSet('Register', 'Unregister')][string]$ElevatedAction)
    $apiDir = Resolve-SolidWorksApiDir
    $quote = {
        param([string]$Value)
        return "'" + $Value.Replace("'", "''") + "'"
    }
    $command = "& $(& $quote $PSCommandPath) -Action $ElevatedAction -RegistrationScope Machine -SolidWorksApiDir $(& $quote $apiDir) -DotNetPath $(& $quote $DotNetPath) -Configuration $(& $quote $Configuration) -ElevatedChild"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded
    ) -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Elevated $ElevatedAction failed or was cancelled. Exit code: $($process.ExitCode)"
    }
}

function Set-RegistryDefaultValue {
    param([string]$Path, [object]$Value, [Microsoft.Win32.RegistryValueKind]$Kind = [Microsoft.Win32.RegistryValueKind]::String)
    $key = New-Item -Path $Path -Force
    $key.SetValue('', $Value, $Kind)
    $key.Close()
}

function Register-CurrentUser {
    $resolvedAssembly = (Resolve-Path $AssemblyPath).Path
    $codeBase = ([Uri]$resolvedAssembly).AbsoluteUri
    $assemblyName = [Reflection.AssemblyName]::GetAssemblyName($resolvedAssembly).FullName
    $classes = 'HKCU:\Software\Classes'
    Set-RegistryDefaultValue "$classes\$ProgId" $ClassName
    Set-RegistryDefaultValue "$classes\$ProgId\CLSID" $AddinGuid
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid" $ClassName
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid\InprocServer32" 'mscoree.dll'
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'ThreadingModel' -Value 'Both' -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'Class' -Value $ClassName -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'Assembly' -Value $assemblyName -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'RuntimeVersion' -Value 'v4.0.30319' -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'CodeBase' -Value $codeBase -PropertyType String -Force | Out-Null
    New-Item "$classes\CLSID\$AddinGuid\InprocServer32\1.0.0.0" -Force | Out-Null
    foreach ($name in @('Class', 'Assembly', 'RuntimeVersion', 'CodeBase')) {
        $value = switch ($name) { 'Class' { $ClassName } 'Assembly' { $assemblyName } 'RuntimeVersion' { 'v4.0.30319' } default { $codeBase } }
        New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32\1.0.0.0" -Name $name -Value $value -PropertyType String -Force | Out-Null
    }
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid\ProgId" $ProgId
    New-Item "$classes\CLSID\$AddinGuid\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}" -Force | Out-Null

}

function Unregister-CurrentUser {
    foreach ($path in @(
        "HKCU:\Software\Classes\$ProgId",
        "HKCU:\Software\Classes\CLSID\$AddinGuid",
        "HKCU:\Software\SOLIDWORKS\Addins\$AddinGuid",
        "HKCU:\Software\SOLIDWORKS\AddInsStartup\$AddinGuid"
    )) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

switch ($Action) {
    'Build' {
        Build-AddinHost
    }
    'Register' {
        if ($RegistrationScope -eq 'Machine') {
            if (-not (Test-IsAdministrator)) {
                if ($ElevatedChild) { throw 'Machine registration did not receive administrator privileges.' }
                Build-AddinHost
                Invoke-ElevatedSelf 'Register'
            } else {
                Build-AddinHost
                if (-not (Test-Path $RegAsmPath)) { throw "64-bit RegAsm not found: $RegAsmPath" }
                & $RegAsmPath $AssemblyPath /codebase
                if ($LASTEXITCODE -ne 0) { throw 'RegAsm registration failed.' }
            }
        } else {
            Build-AddinHost
            Register-CurrentUser
        }
    }
    'ComSmoke' {
        if (-not (Test-Path "HKCU:\Software\Classes\CLSID\$AddinGuid\InprocServer32") -and
            -not (Test-Path "HKLM:\Software\Classes\CLSID\$AddinGuid\InprocServer32")) {
            throw 'COM class is not registered. Run Register first.'
        }
        $instance = New-Object -ComObject $ProgId
        if (-not $instance) { throw 'COM activation returned no object.' }
        if ([Runtime.InteropServices.Marshal]::IsComObject($instance)) {
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($instance) | Out-Null
        }
    }
    'Probe' {
        if (-not (Test-Path $AssemblyPath)) { Build-AddinHost }
        if (-not (Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid")) {
            throw 'HKLM SolidWorks Add-ins registration is missing. Run an elevated Machine registration before the in-process probe.'
        }
        & python (Join-Path $ProjectRoot 'tests\solidworks_addin_host_regression.py') --assembly $AssemblyPath --start
        if ($LASTEXITCODE -ne 0) { throw 'SolidWorks Add-in live probe failed.' }
    }
    'Unregister' {
        if ($RegistrationScope -eq 'Machine') {
            if (-not (Test-IsAdministrator)) {
                if ($ElevatedChild) { throw 'Machine unregister did not receive administrator privileges.' }
                Invoke-ElevatedSelf 'Unregister'
            } else {
                if (-not (Test-Path $RegAsmPath)) { throw "64-bit RegAsm not found: $RegAsmPath" }
                & $RegAsmPath $AssemblyPath /unregister
                if ($LASTEXITCODE -ne 0) { throw 'RegAsm unregister failed.' }
            }
        } else {
            Unregister-CurrentUser
        }
    }
}

[pscustomobject]@{
    action = $Action
    scope = $RegistrationScope
    assembly = $AssemblyPath
    com_registered = (Test-Path "HKCU:\Software\Classes\CLSID\$AddinGuid\InprocServer32") -or (Test-Path "HKLM:\Software\Classes\CLSID\$AddinGuid\InprocServer32")
    solidworks_discovery_registered = Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid"
    in_process_probe_ready = (Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid") -and (Get-Process SLDWORKS -ErrorAction SilentlyContinue)
}
