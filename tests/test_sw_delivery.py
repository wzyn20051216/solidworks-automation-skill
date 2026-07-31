"""BOM 与 Pack and Go 的无 COM 回归测试。"""
from pathlib import Path

from scripts import sw_delivery


class FakeReferencedModel:
    def __init__(self, properties):
        self.properties = properties


class FakeComponent:
    def __init__(self, path, configuration, name, properties, excluded=False):
        self.path = str(path)
        self.ReferencedConfiguration = configuration
        self.Name2 = name
        self.ExcludeFromBOM = excluded
        self.model = FakeReferencedModel(properties)

    def GetPathName(self):
        return self.path

    def GetModelDoc2(self):
        return self.model


class FakePackAndGo:
    def __init__(self, count=2):
        self.count = count
        self.target = None

    def GetDocumentNamesCount(self):
        return self.count

    def SetSaveToName(self, _folder_mode, target):
        self.target = Path(target)
        return True


class FakeExtension:
    def __init__(self, source):
        self.package = FakePackAndGo()
        self.source = source

    def GetPackAndGo(self):
        return self.package

    def SavePackAndGo(self, package):
        package.target.mkdir(parents=True, exist_ok=True)
        (package.target / self.source.name).write_bytes(b"assembly")
        (package.target / "part.sldprt").write_bytes(b"part")
        return [0, 0]


class FakeAssembly:
    def __init__(self, source, components):
        self.source = str(source)
        self.components = components
        self.Extension = FakeExtension(Path(source))

    def GetType(self):
        return 2

    def GetComponents(self, _top_level_only):
        return self.components

    def GetPathName(self):
        return self.source


def fake_property_reader(model, name, configuration_name=""):
    value = model.properties.get((configuration_name, name), model.properties.get(("", name), ""))
    return {"exists": bool(value), "resolved": value, "raw": value}


def test_bom_groups_same_part_and_excludes_marked_component(tmp_path, monkeypatch):
    part = tmp_path / "part.sldprt"
    part.write_text("part", encoding="utf-8")
    properties = {("默认", "PartNumber"): "PN-100", ("", "Description"): "安装块"}
    components = [
        FakeComponent(part, "默认", "part-1", properties),
        FakeComponent(part, "默认", "part-2", properties),
        FakeComponent(tmp_path / "hidden.sldprt", "默认", "hidden-1", {}, excluded=True),
    ]
    assembly_path = tmp_path / "assembly.sldasm"
    assembly_path.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(assembly_path, components)
    monkeypatch.setattr(sw_delivery, "read_custom_property", fake_property_reader)

    report = sw_delivery.export_assembly_bom_csv(model, tmp_path / "bom.csv")

    assert report["success"] is True
    assert report["row_count"] == 1
    assert report["quantity_total"] == 2
    assert report["rows"][0]["part_number"] == "PN-100"
    assert report["review_required"] is True
    assert (tmp_path / "bom.csv").read_text(encoding="utf-8-sig").startswith("item,part_number")


def test_pack_and_go_uses_native_api_and_records_outputs(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(source, [])
    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["document_count"] == 2
    assert report["status_codes"] == [0, 0]
    assert report["produced_count"] == 2
    assert all(item["produced_this_run"] for item in report["outputs"])


def test_pack_and_go_rejects_nonempty_target_by_default(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    target = tmp_path / "package"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    model = FakeAssembly(source, [])

    try:
        sw_delivery.pack_and_go(model, target)
    except FileExistsError as error:
        assert "目标目录非空" in str(error)
    else:
        raise AssertionError("nonempty target must require overwrite")
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
