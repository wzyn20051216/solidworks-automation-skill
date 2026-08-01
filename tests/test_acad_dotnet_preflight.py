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


def test_dotnet_preflight_keeps_unverified_runtime_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(_MODULE, "discover_installation", lambda _product: {"installed": True, "executable": r"D:\AutoCAD 2024\acad.exe", "source": "test"})
    monkeypatch.setattr(_MODULE, "_sdk_info", lambda: {"dotnet": "dotnet", "sdk_versions": ["8.0.0"], "msbuild": "msbuild"})
    monkeypatch.setattr(_MODULE, "_find_managed_api", lambda _installation: [
        r"D:\AutoCAD 2024\AcCoreMgd.dll",
        r"D:\AutoCAD 2024\AcDbMgd.dll",
        r"D:\AutoCAD 2024\AcMgd.dll",
    ])
    report = run_preflight(evidence_path=tmp_path / "missing.json")
    assert report["backends"]["autocad_dotnet"]["status"] == "blocked"
    assert report["backends"]["autocad_dotnet"]["error_code"] == "AUTOCAD_DOTNET_RUNTIME_NOT_VERIFIED"


def test_dotnet_preflight_marks_complete_runtime_evidence_as_pilot(monkeypatch, tmp_path):
    monkeypatch.setattr(_MODULE, "discover_installation", lambda _product: {"installed": True, "executable": r"D:\AutoCAD 2024\acad.exe", "source": "test"})
    monkeypatch.setattr(_MODULE, "_sdk_info", lambda: {"dotnet": "dotnet", "sdk_versions": ["8.0.0"], "msbuild": None})
    monkeypatch.setattr(_MODULE, "_find_managed_api", lambda _installation: [
        r"D:\AutoCAD 2024\AcCoreMgd.dll",
        r"D:\AutoCAD 2024\AcDbMgd.dll",
        r"D:\AutoCAD 2024\AcMgd.dll",
    ])
    evidence = tmp_path / "runtime.json"
    import hashlib
    artifacts = []
    for suffix in _MODULE.REQUIRED_ARTIFACT_SUFFIXES:
        artifact = tmp_path / f"artifact{suffix}"
        artifact.write_bytes(b"verified-artifact")
        artifacts.append({
            "path": str(artifact),
            "size": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        })
    evidence.write_text(__import__("json").dumps({
        "backend": "autocad_dotnet",
        "status": "pass",
        "checks": {check: True for check in _MODULE.RUNTIME_REQUIRED_CHECKS},
        "artifactLedger": artifacts,
    }), encoding="utf-8")
    report = run_preflight(evidence_path=evidence)
    assert report["backends"]["autocad_dotnet"]["status"] == "pilot"


def test_sdk_info_skips_runtime_only_dotnet(monkeypatch, tmp_path):
    runtime_only = tmp_path / "runtime" / "dotnet.exe"
    user_sdk = tmp_path / "user" / "Microsoft" / "dotnet" / "dotnet.exe"
    runtime_only.parent.mkdir(parents=True)
    user_sdk.parent.mkdir(parents=True)
    runtime_only.touch()
    user_sdk.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "program-files"))
    monkeypatch.setattr(_MODULE.shutil, "which", lambda _name: str(runtime_only))

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(_MODULE.subprocess, "run", lambda command, **_kwargs: Result("8.0.423 [sdk]\n" if Path(command[0]) == user_sdk else ""))
    sdk = _MODULE._sdk_info()
    assert Path(sdk["dotnet"]) == user_sdk
    assert sdk["sdk_versions"] == ["8.0.423 [sdk]"]


def test_dotnet_preflight_blocks_tampered_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(_MODULE, "discover_installation", lambda _product: {"installed": True, "executable": r"D:\AutoCAD 2024\acad.exe"})
    monkeypatch.setattr(_MODULE, "_sdk_info", lambda: {"dotnet": "dotnet", "sdk_versions": ["8.0.423"], "msbuild": None})
    monkeypatch.setattr(_MODULE, "_find_managed_api", lambda _installation: [
        r"D:\AutoCAD 2024\AcCoreMgd.dll", r"D:\AutoCAD 2024\AcDbMgd.dll", r"D:\AutoCAD 2024\AcMgd.dll",
    ])
    evidence = tmp_path / "runtime.json"
    artifacts = []
    import hashlib
    for suffix in _MODULE.REQUIRED_ARTIFACT_SUFFIXES:
        artifact = tmp_path / f"artifact{suffix}"
        artifact.write_bytes(b"before")
        artifacts.append({"path": str(artifact), "size": 6, "sha256": hashlib.sha256(b"before").hexdigest()})
    evidence.write_text(__import__("json").dumps({
        "backend": "autocad_dotnet", "status": "pass",
        "checks": {check: True for check in _MODULE.RUNTIME_REQUIRED_CHECKS}, "artifactLedger": artifacts,
    }), encoding="utf-8")
    (tmp_path / "artifact.dwg").write_bytes(b"after!")
    report = run_preflight(evidence_path=evidence)
    assert report["backends"]["autocad_dotnet"]["status"] == "blocked"
    assert report["runtime_evidence"]["artifact_errors"]
