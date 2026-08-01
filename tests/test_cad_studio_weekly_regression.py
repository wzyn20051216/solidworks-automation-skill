import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "tests" / "cad_studio_weekly_regression.py"
_SPEC = importlib.util.spec_from_file_location("cad_studio_weekly_regression", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)


def test_weekly_regression_decodes_python_and_autocad_output():
    assert _MODULE._decode_output("测试通过".encode("utf-8")) == "测试通过"
    assert _MODULE._decode_output("中文输出".encode("gb18030")) == "中文输出"
    assert _MODULE._decode_output("未知命令".encode("utf-16")) == "未知命令"
