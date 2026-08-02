"""BOM 与 Pack and Go 的无 COM 回归测试。"""
from pathlib import Path

from scripts import sw_delivery


class FakeReferencedModel:
    def __init__(self, properties):
        self.properties = properties


class FakeComponent:
    def __init__(self, path, configuration, name, properties, excluded=False, suppression=2, toolbox_type=0):
        self.path = str(path)
        self.ReferencedConfiguration = configuration
        self.Name2 = name
        self.ExcludeFromBOM = excluded
        self.model = FakeReferencedModel(properties)
        self.model.Extension = type("Extension", (), {"ToolboxPartType": toolbox_type})()
        self.suppression = suppression

    def GetPathName(self):
        return self.path

    def GetModelDoc2(self):
        return self.model

    def GetSuppression(self):
        return self.suppression


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


class FakePropertyPackAndGo(FakePackAndGo):
    """@brief 模拟 SW2024 将无参 GetDocumentNamesCount 暴露为伪属性。"""

    GetDocumentNamesCount = 2


class FakePropertyExtension(FakeExtension):
    """@brief 模拟 SW2024 将无参 GetPackAndGo 暴露为伪属性。"""

    def __init__(self, source):
        super().__init__(source)
        self.package = FakePropertyPackAndGo()

    @property
    def GetPackAndGo(self):
        return self.package


class FakeByRefExtension(FakeExtension):
    """@brief 模拟需要显式 by-ref 输出参数的 GetPackAndGo。"""

    def GetPackAndGo(self, output):
        output.value = self.package
        return None


class FakeFailingZeroArgByRefExtension(FakeByRefExtension):
    """@brief 模拟零参数调用失败、by-ref 调用成功的 COM 包装。"""

    def __getattribute__(self, name):
        if name == "GetPackAndGo":
            def getter(*args):
                if not args:
                    raise TypeError("缺少必要的 by-ref 输出参数")
                return FakeByRefExtension.GetPackAndGo(self, *args)

            return getter
        return super().__getattribute__(name)


class FakeVariant:
    """@brief 测试专用 VARIANT，记录 by-ref 输出值。"""

    def __init__(self, _variant_type, value):
        self.value = value


class FakeRawOleObject:
    """@brief 模拟官方 TLB 的无参数、直接返回 IDispatch 调用。"""

    def __init__(self, package):
        self.package = package

    def GetIDsOfNames(self, name):
        assert name == "GetPackAndGo"
        return 207

    def InvokeTypes(self, dispid, lcid, dispatch_kind, return_type, argument_types):
        assert dispid == 207
        assert lcid == 0
        assert dispatch_kind == sw_delivery.pythoncom.DISPATCH_METHOD
        assert return_type == (sw_delivery.pythoncom.VT_DISPATCH, 0)
        assert argument_types == ()
        return self.package


class FakeRawExtension(FakeExtension):
    """@brief 模拟动态调用失败但底层官方签名可用的 pywin32 包装。"""

    def __init__(self, source):
        super().__init__(source)
        self._oleobj_ = FakeRawOleObject(self.package)

    def GetPackAndGo(self):
        raise TypeError("动态代理未正确封送直接返回接口")


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


class FakeDependencyAssembly(FakeAssembly):
    """@brief 提供 GetDependencies2，用于验证 Pack and Go 漏包门禁。"""

    def __init__(self, source, components, dependencies):
        super().__init__(source, components)
        self.dependencies = dependencies

    def GetDependencies2(self, *_args):
        values = []
        for path in self.dependencies:
            values.extend([Path(path).stem, str(path)])
        return tuple(values)


class FakeOleAssembly(FakeAssembly):
    """@brief 提供 _oleobj_，用于验证强类型父文档包装。"""

    def __init__(self, source, components):
        super().__init__(source, components)
        self._oleobj_ = object()


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


def test_pack_and_go_accepts_sw2024_pseudo_properties(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(source, [])
    model.Extension = FakePropertyExtension(source)

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["document_count"] == 2


def test_pack_and_go_accepts_byref_packandgo_output(tmp_path, monkeypatch):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(source, [])
    model.Extension = FakeFailingZeroArgByRefExtension(source)
    monkeypatch.setattr(sw_delivery, "_VARIANT", FakeVariant)

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["document_count"] == 2


def test_pack_and_go_uses_official_noarg_invoketypes_signature(tmp_path):
    """@brief 动态代理失败时按 TLB 的直接 IDispatch 返回值获取对象。"""
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(source, [])
    model.Extension = FakeRawExtension(source)

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["backend"] == "pywin32"
    assert report["document_count"] == 2


def test_comtypes_connection_does_not_own_active_instance():
    """@brief 已有实例必须只附着，不能误标为本次启动。"""
    active = object()

    class FakeClient:
        @staticmethod
        def GetActiveObject(progid):
            assert progid == "SldWorks.Application.34"
            return active

        @staticmethod
        def CreateObject(_progid):
            raise AssertionError("已有活动实例时不得创建新实例")

    app, started_here, error = sw_delivery._connect_comtypes_solidworks(
        FakeClient,
        ["SldWorks.Application.34"],
    )

    assert app is active
    assert started_here is False
    assert error is None


def test_comtypes_connection_owns_only_fallback_created_instance():
    """@brief 无活动实例时才允许创建并取得退出所有权。"""
    created = object()

    class FakeClient:
        @staticmethod
        def GetActiveObject(_progid):
            raise RuntimeError("not running")

        @staticmethod
        def CreateObject(progid):
            assert progid == "SldWorks.Application.34"
            return created

    app, started_here, error = sw_delivery._connect_comtypes_solidworks(
        FakeClient,
        ["SldWorks.Application.34"],
    )

    assert app is created
    assert started_here is True
    assert "not running" in str(error)


def test_pack_and_go_falls_back_to_comtypes_backend(tmp_path, monkeypatch):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeAssembly(source, [])

    def failing_pywin32(*_args, **_kwargs):
        raise RuntimeError("pywin32 GetPackAndGo failed")

    def fake_comtypes(_source_path, target, existing_files, **_kwargs):
        output = target / "assembly.sldasm"
        output.write_bytes(b"assembly")
        return {
            "backend": "comtypes",
            "document_count": 1,
            "status_codes": [0],
            "outputs": sw_delivery._collect_new_outputs(target, existing_files),
            "produced_count": 1,
        }

    monkeypatch.setattr(sw_delivery, "_pywin32_pack_and_go", failing_pywin32)
    monkeypatch.setattr(sw_delivery, "_comtypes_pack_and_go", fake_comtypes)

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["backend"] == "comtypes"
    assert report["fallback_errors"] == ["pywin32: pywin32 GetPackAndGo failed"]


def test_pack_and_go_stages_dependencies_when_native_package_misses_dependencies(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    dependency = tmp_path / "needed.sldprt"
    dependency.write_text("part", encoding="utf-8")
    model = FakeDependencyAssembly(source, [], [dependency])

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["success"] is True
    assert report["status"] == "pilot"
    assert report["backend"] == "solidworks-native+staged_dependencies"
    assert report["error_code"] == "SW_PACK_AND_GO_NATIVE_ENUMERATION_INCOMPLETE"
    assert report["manual_review_required"] is True
    assert report["missing_dependencies"] == []
    assert report["native_missing_dependencies"] == [str(dependency)]
    assert report["fallback_used"] is True
    manifest = Path(report["manifest"])
    assert manifest.is_file()
    assert {Path(item["path"]).name for item in report["outputs"]} >= {source.name, dependency.name, manifest.name}
    assert report["status_codes"] == [0, 0]


def test_pack_and_go_can_strictly_block_native_dependency_gap(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    dependency = tmp_path / "needed.sldprt"
    dependency.write_text("part", encoding="utf-8")
    model = FakeDependencyAssembly(source, [], [dependency])

    report = sw_delivery.pack_and_go(model, tmp_path / "package", fallback_policy="blocked")

    assert report["success"] is False
    assert report["status"] == "blocked"
    assert report["error_code"] == "SW_PACK_AND_GO_DEPENDENCY_ENUMERATION_INCOMPLETE"
    assert report["fallback_used"] is False
    assert report["missing_dependencies"] == [str(dependency)]
    assert report["fallback_policy"] == "blocked"


def test_pack_and_go_rejects_staged_destination_name_collision(tmp_path):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    first_root = tmp_path / "one"
    second_root = tmp_path / "two"
    first_root.mkdir()
    second_root.mkdir()
    first = first_root / "same.sldprt"
    second = second_root / "same.sldprt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    model = FakeDependencyAssembly(source, [], [first, second])

    report = sw_delivery.pack_and_go(model, tmp_path / "package", flatten=True)

    assert report["success"] is False
    assert report["status"] == "blocked"
    assert report["error_code"] == "SW_PACK_AND_GO_DEPENDENCY_ENUMERATION_INCOMPLETE"
    assert any("重名冲突" in item for item in report["fallback_errors"])


def test_model_doc_extension_wraps_parent_with_generated_interface(tmp_path, monkeypatch):
    source = tmp_path / "assembly.sldasm"
    source.write_text("assembly", encoding="utf-8")
    model = FakeOleAssembly(source, [])
    expected_extension = model.Extension

    class FakeTypedModel:
        def __init__(self, ole_object):
            assert ole_object is model._oleobj_
            self.Extension = expected_extension

    class FakeTypeLibraryModule:
        IModelDoc2 = FakeTypedModel

    monkeypatch.setattr(
        sw_delivery,
        "_load_sldworks_typelib_module",
        lambda: FakeTypeLibraryModule,
    )

    assert sw_delivery._model_doc_extension(model) is expected_extension


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


def test_pack_audit_matrix_records_external_toolbox_configuration_and_lightweight(tmp_path):
    """@brief 审计矩阵必须保留外部、Toolbox、配置和轻化组件的独立证据。"""
    project = tmp_path / "project"
    external = tmp_path / "vendor" / "toolbox" / "bolt.sldprt"
    source = project / "assembly.sldasm"
    drawing = project / "assembly.slddrw"
    output_dir = tmp_path / "package"
    project.mkdir()
    external.parent.mkdir(parents=True)
    output_dir.mkdir()
    source.write_text("assembly", encoding="utf-8")
    drawing.write_text("drawing", encoding="utf-8")
    external.write_text("bolt", encoding="utf-8")
    output_paths = []
    for path in (source, drawing, external):
        target = output_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        output_paths.append({"path": str(target), "produced_this_run": True})
    component = FakeComponent(external, "M6x20", "bolt-1", {}, suppression=1, toolbox_type=1)
    records = sw_delivery._collect_component_audit_records(FakeAssembly(source, [component]), str(source))

    result = sw_delivery.build_pack_and_go_audit_matrix(
        str(source), [str(external)], records, [str(drawing)], output_paths,
        include_drawings=True, include_toolbox_components=True, include_suppressed=False,
    )

    bolt = next(row for row in result["rows"] if row["file_name"] == external.name)
    assert result["status"] == "review_required"
    assert result["blocking_error_codes"] == []
    assert bolt["external_reference"] is True
    assert bolt["configurations"] == ["M6x20"]
    assert bolt["load_states"] == ["lightweight"]
    assert bolt["toolbox_states"] == ["standard"]
    assert result["summary"]["associated_drawing_count"] == 1


def test_pack_audit_matrix_blocks_missing_associated_drawing(tmp_path):
    """@brief include_drawings 为真时，同名真实工程图漏包必须阻断。"""
    source = tmp_path / "assembly.sldasm"
    drawing = tmp_path / "assembly.slddrw"
    output = tmp_path / "package" / source.name
    source.write_text("assembly", encoding="utf-8")
    drawing.write_text("drawing", encoding="utf-8")
    output.parent.mkdir()
    output.write_text("assembly", encoding="utf-8")

    result = sw_delivery.build_pack_and_go_audit_matrix(
        str(source), [], [], [str(drawing)], [{"path": str(output), "produced_this_run": True}],
        include_drawings=True, include_toolbox_components=True, include_suppressed=False,
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "SW_PACK_AUDIT_ASSOCIATED_DRAWING_MISSING"
    drawing_row = next(row for row in result["rows"] if row["reference_kind"] == "associated_drawing")
    assert drawing_row["required"] is True
    assert drawing_row["included"] is False


def test_pack_audit_matrix_respects_toolbox_and_suppressed_options(tmp_path):
    """@brief 未请求 Toolbox/压缩组件时，不得把对应缺文件误判为漏包。"""
    source = tmp_path / "assembly.sldasm"
    toolbox = tmp_path / "toolbox" / "bolt.sldprt"
    suppressed = tmp_path / "hidden.sldprt"
    output = tmp_path / "package" / source.name
    source.write_text("assembly", encoding="utf-8")
    toolbox.parent.mkdir()
    toolbox.write_text("bolt", encoding="utf-8")
    suppressed.write_text("hidden", encoding="utf-8")
    output.parent.mkdir()
    output.write_text("assembly", encoding="utf-8")
    components = [
        FakeComponent(toolbox, "M6", "bolt", {}, suppression=2, toolbox_type=1),
        FakeComponent(suppressed, "默认", "hidden", {}, suppression=0, toolbox_type=0),
    ]
    records = sw_delivery._collect_component_audit_records(FakeAssembly(source, components), str(source))

    result = sw_delivery.build_pack_and_go_audit_matrix(
        str(source), [str(toolbox), str(suppressed)], records, [], [{"path": str(output), "produced_this_run": True}],
        include_drawings=False, include_toolbox_components=False, include_suppressed=False,
    )

    dependency_rows = [row for row in result["rows"] if row["reference_kind"] == "model_dependency"]
    assert result["blocking_error_codes"] == []
    assert all(row["required"] is False for row in dependency_rows)


def test_pack_and_go_report_exposes_stable_audit_matrix(tmp_path):
    """@brief Pack and Go 公共结果必须附带原生与最终审计矩阵。"""
    source = tmp_path / "assembly.sldasm"
    part = tmp_path / "part.sldprt"
    source.write_text("assembly", encoding="utf-8")
    part.write_text("part", encoding="utf-8")
    component = FakeComponent(part, "默认", "part-1", {})
    model = FakeDependencyAssembly(source, [component], [part])

    report = sw_delivery.pack_and_go(model, tmp_path / "package")

    assert report["audit_matrix"]["schema_version"] == "1.0"
    assert report["native_audit_matrix"]["summary"]["required_count"] == 2
    assert report["component_audit"][0]["configuration"] == "默认"
    assert report["associated_drawings"] == []
