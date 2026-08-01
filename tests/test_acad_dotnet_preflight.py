import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "subskills" / "autocad-automation" / "scripts" / "acad_dotnet_preflight.py"
_SPEC = importlib.util.spec_from_file_location("acad_dotnet_preflight", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)
run_preflight = _MODULE.run_preflight


def test_dotnet_preflight_keeps_missing_managed_api_blocked(monkeypatch):
    monkeypatch.setattr(_MODULE, "discover_installation", lambda _product: {"installed": True, "executable": r"D:\AutoCAD 2024\acad.exe", "source": "test"})
    monkeypatch.setattr(_MODULE, "_sdk_info", lambda: {"dotnet": "dotnet", "sdk_versions": ["8.0.0"], "msbuild": None})
    monkeypatch.setattr(_MODULE, "_find_managed_api", lambda _installation: [])
    report = run_preflight()
    assert report["backends"]["autocad_dotnet"]["status"] == "blocked"
    assert report["backends"]["autocad_dotnet"]["error_code"] == "AUTOCAD_DOTNET_PREREQUISITE_MISSING"


def test_dotnet_preflight_marks_local_managed_api_as_pilot(monkeypatch):
    monkeypatch.setattr(_MODULE, "discover_installation", lambda _product: {"installed": True, "executable": r"D:\AutoCAD 2024\acad.exe", "source": "test"})
    monkeypatch.setattr(_MODULE, "_sdk_info", lambda: {"dotnet": "dotnet", "sdk_versions": ["8.0.0"], "msbuild": "msbuild"})
    monkeypatch.setattr(_MODULE, "_find_managed_api", lambda _installation: [r"D:\AutoCAD 2024\AcMgd.dll"])
    report = run_preflight()
    assert report["backends"]["autocad_dotnet"]["status"] == "pilot"
