"""SolidWorks 文档打开兼容路径测试。"""
from pathlib import Path

from scripts import sw_connect


class FakeModel:
    """@brief 最小文档对象。"""


def test_open_document_reuses_existing_model(tmp_path):
    """@brief 装配体已加载组件时不重复调用 OpenDoc6。"""
    source = tmp_path / "part.sldprt"
    source.write_bytes(b"part")
    expected = FakeModel()

    class FakeSolidWorks:
        def GetOpenDocumentByName(self, path):
            assert Path(path) == source.resolve()
            return expected

        def OpenDoc6(self, *_args):
            raise AssertionError("不应重复打开已加载文档")

    assert sw_connect.open_document(FakeSolidWorks(), source) is expected


def test_open_document_falls_back_to_dynamic_proxy(tmp_path, monkeypatch):
    """@brief makepy 拒绝 by-ref VARIANT 时使用动态代理。"""
    source = tmp_path / "part.sldprt"
    source.write_bytes(b"part")
    expected = FakeModel()

    class GeneratedSolidWorks:
        _oleobj_ = object()

        def GetOpenDocumentByName(self, _path):
            return None

        def OpenDoc6(self, *_args):
            raise TypeError("int() argument must not be VARIANT")

    class DynamicSolidWorks:
        def OpenDoc6(self, _path, _doc_type, _options, _configuration, errors, warnings):
            errors.value = 0
            warnings.value = 0
            return expected

    monkeypatch.setattr(
        sw_connect.win32com_client.dynamic,
        "DumbDispatch",
        lambda ole_object, _name: DynamicSolidWorks() if ole_object is GeneratedSolidWorks._oleobj_ else None,
    )

    assert sw_connect.open_document(GeneratedSolidWorks(), source, silent=True) is expected
