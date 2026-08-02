import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "subskills" / "autocad-automation" / "scripts" / "acad_dotnet_regression.py"
_SPEC = importlib.util.spec_from_file_location("acad_dotnet_regression", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)


def test_dotnet_script_contains_only_fixed_bridge_commands(tmp_path):
    text = _MODULE._script_text(tmp_path / "CadStudio.AutoCAD2024.dll", {"SECURELOAD": 2, "FILEDIA": 1, "BACKGROUNDPLOT": 3})
    lines = [line for line in text.splitlines() if line]
    assert lines[:7] == ["_.SECURELOAD", "0", "_.FILEDIA", "0", "_.BACKGROUNDPLOT", "0", "_.NETLOAD"]
    assert "CADSTUDIOPROBE" in lines
    assert "CADSTUDIOCREATE" in lines
    assert "_.BACKGROUNDPLOT" in lines
    assert "_.EXPORTPDF" not in lines
    assert "_.PNGOUT" not in lines
    assert lines[-8:] == ["_.SECURELOAD", "2", "_.FILEDIA", "1", "_.BACKGROUNDPLOT", "3", "_.QUIT", "_Y"]
    assert "(command" not in text
    assert "AutoLISP" not in text


def test_runtime_stays_blocked_until_every_required_check_passes():
    checks = {name: True for name in _MODULE.REQUIRED_CHECKS}
    checks["png_generated"] = False
    status, missing = _MODULE._runtime_status({"status": "review_required", "checks": checks}, {"returncode": 0})
    assert status == "blocked"
    assert missing == ["png_generated"]


def test_runtime_pass_requires_successful_process_and_report():
    checks = {name: True for name in _MODULE.REQUIRED_CHECKS}
    assert _MODULE._runtime_status({"status": "pass", "checks": checks}, {"returncode": 0}) == ("pass", [])
    assert _MODULE._runtime_status({"status": "pass", "checks": checks}, {"returncode": 1})[0] == "failed"


def test_process_output_decodes_utf8_and_autocad_utf16():
    assert _MODULE._decode_output("生成成功".encode("utf-8")) == "生成成功"
    assert _MODULE._decode_output("中文输出".encode("gb18030")) == "中文输出"
    assert _MODULE._decode_output("未知命令".encode("utf-16")) == "未知命令"


def test_secureload_probe_parses_and_restores_supported_values(tmp_path):
    assert _MODULE._parse_system_variable("输入 SECURELOAD 的新值 <2>:", "SECURELOAD") == 2
    assert _MODULE._parse_system_variable("Enter new value for FILEDIA <1>:", "FILEDIA") == 1
    assert _MODULE._parse_system_variable("no matching prompt", "BACKGROUNDPLOT") is None
    text = _MODULE._script_text(tmp_path / "plugin.dll", {"SECURELOAD": 1, "FILEDIA": 0, "BACKGROUNDPLOT": 2})
    assert "_.SECURELOAD\n1\n_.FILEDIA\n0\n_.BACKGROUNDPLOT\n2\n_.QUIT" in text


def test_persist_result_records_failed_run_in_history(tmp_path, monkeypatch):
    """@brief 前置或构建失败也必须写 final report 和历史。"""
    monkeypatch.setattr(_MODULE, "ROOT", tmp_path)
    run_dir = tmp_path / "output" / "autocad-dotnet" / "20260802T000000Z"
    run_dir.mkdir(parents=True)
    result = {
        "backend": "autocad_dotnet",
        "status": "failed",
        "stage": "build",
        "error_code": "AUTOCAD_DOTNET_BUILD_FAILED",
        "generatedAt": "2026-08-02T00:00:00+00:00",
        "artifacts": [],
    }

    persisted = _MODULE._persist_result(result, run_dir)

    final_report = run_dir / "final-report.json"
    history = __import__("json").loads((tmp_path / "output" / "autocad-dotnet" / "runtime-history.json").read_text(encoding="utf-8"))
    assert final_report.is_file()
    assert persisted["artifacts"] == [str(final_report)]
    assert history["runs"][0]["status"] == "failed"
    assert history["runs"][0]["error_code"] == "AUTOCAD_DOTNET_BUILD_FAILED"
