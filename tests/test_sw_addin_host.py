"""@brief C# SolidWorks Add-in 宿主的离线契约测试。"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
PROJECT = ROOT / "dotnet" / "CadStudio.SolidWorks.AddinHost"


def _read(name: str) -> str:
    """@brief 读取 Add-in 源文件。"""
    return (PROJECT / name).read_text(encoding="utf-8")


def test_addin_uses_real_iswaddin_contract_and_callback_registration() -> None:
    source = _read("SwAddin.cs")
    assert "public sealed class SwAddin : ISwAddin" in source
    assert "public bool ConnectToSW(object thisSw, int cookie)" in source
    assert "public bool DisconnectFromSW()" in source
    assert "SetAddinCallbackInfo2" in source
    assert "if (!callbackReady)" in source
    assert "ReleaseHostResources" in source


def test_host_covers_events_pmp_taskpane_commands_and_diagnostics() -> None:
    source = _read("SwAddin.cs")
    assert "private SldWorks applicationEvents" in source
    assert "applicationEvents = (SldWorks)swApp" in source
    assert "ICreatePropertyManagerPage" in source
    assert "DisplayWindowFromHandlex64" in source
    assert "CreateCommandGroup2" in source
    assert "host-status.json" in _read("HostDiagnostics.cs")
    assert 'diagnostics.RecordEvent("constructed")' in source
    assert "swCreateCommandGroupErrors.swCreateCommandGroup_Success" in source


def test_property_page_handler_implements_all_sw2026_callbacks() -> None:
    source = _read("PropertyPageHandler.cs")
    assert "[ComVisible(true)]" in source
    assert "[ClassInterface(ClassInterfaceType.AutoDispatch)]" in source
    public_callbacks = set(re.findall(r"public\s+(?:void|bool|int)\s+(On\w+|After\w+)\s*\(", source))
    assert len(public_callbacks) == 37
    assert {"AfterActivation", "AfterClose", "OnSubmitSelection", "OnWindowFromHandleControlCreated"} <= public_callbacks


def test_project_targets_64_bit_net48_and_local_pia_directory() -> None:
    project = _read("CadStudio.SolidWorks.AddinHost.csproj")
    assert "<TargetFramework>net48</TargetFramework>" in project
    assert "<PlatformTarget>x64</PlatformTarget>" in project
    assert "$(SolidWorksApiDir)" in project
    assert "SolidWorks.Interop.swpublished.dll" in project
    assert "<SignAssembly>true</SignAssembly>" in project
    assert '[assembly: Guid("AF071B05-0956-3EFB-B3F0-77BC51751AC9")]' in _read("Properties/AssemblyInfo.cs")


def test_registration_script_elevates_only_machine_operations_and_probe_can_start_host() -> None:
    script = (ROOT / "scripts" / "sw_addin_host.ps1").read_text(encoding="utf-8")
    assert "Test-IsAdministrator" in script
    assert "Invoke-ElevatedSelf 'Register'" in script
    assert "Invoke-ElevatedSelf 'Unregister'" in script
    assert '"/tlb:$TypeLibraryPath"' in script
    assert "--assembly $AssemblyPath --start" in script
