"""SolidWorks 工程图兼容入口。

工程图实现已归档到 ``subskills/solidworks-engineering-drawing``。该桥接文件保留
历史 ``scripts.sw_drawing`` 导入路径，避免已有 Skill、测试和第三方调用失效。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "subskills"
    / "solidworks-engineering-drawing"
    / "scripts"
    / "drawing_workflow.py"
)
_SPEC = importlib.util.spec_from_file_location("solidworks_drawing_workflow", _IMPLEMENTATION)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"无法加载工程图子技能实现: {_IMPLEMENTATION}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

__all__ = list(getattr(_MODULE, "__all__", ()))
if not __all__:
    __all__ = [name for name in vars(_MODULE) if not name.startswith("_")]
for _name in __all__:
    globals()[_name] = getattr(_MODULE, _name)
