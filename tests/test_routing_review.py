from scripts import routing_review


def test_review_routing_file_returns_stable_blocked_for_missing_input(tmp_path):
    """@brief 输入缺失时返回结构化 blocked，而不是抛出 FileNotFoundError。"""
    report = routing_review.review_routing_file(tmp_path / "missing.json", tmp_path / "report.json")
    assert report["status"] == "blocked"
    assert report["stage"] == "input_validation"
    assert report["error_code"] == "routing_input_missing"
    assert not (tmp_path / "report.json").exists()


def test_review_routing_file_rejects_invalid_root_and_json(tmp_path):
    """@brief 损坏 JSON 或非 object 根节点必须被阻断。"""
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{broken", encoding="utf-8")
    report = routing_review.review_routing_file(invalid, tmp_path / "invalid-report.json")
    assert report["error_code"] == "routing_input_invalid_json"

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    report = routing_review.review_routing_file(array, tmp_path / "array-report.json")
    assert report["error_code"] == "routing_input_root_invalid"


def test_review_routing_file_rejects_oversized_input(tmp_path, monkeypatch):
    """@brief 超过输入上限时不解析、不写报告。"""
    source = tmp_path / "large.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routing_review, "_MAX_INPUT_BYTES", 1)
    report = routing_review.review_routing_file(source, tmp_path / "large-report.json")
    assert report["status"] == "blocked"
    assert report["error_code"] == "routing_input_too_large"
    assert not (tmp_path / "large-report.json").exists()


def test_routing_report_calculates_lengths_and_endpoint_table(monkeypatch):
    """@brief 中性路由必须给出端点、分段长度和明确的原生前置。"""
    monkeypatch.setattr(routing_review, "probe_solidworks_routing", lambda: {"status": "blocked", "readyForNativeWrite": False})
    report = routing_review.build_routing_report({
        "routeType": "cable",
        "units": "mm",
        "minimumBendRadius": 20,
        "minimumClearance": 5,
        "maximumSupportSpacing": 60,
        "material": "PVC",
        "endpoints": [
            {"id": "J1", "position": [0, 0, 0]},
            {"id": "J2", "position": [30, 40, 0]},
        ],
        "segments": [{"id": "S1", "start": "J1", "end": "J2", "bendRadius": 25, "diameter": 8}],
    })

    assert report["status"] == "review_required"
    assert report["totalLength"] == 50
    assert report["segmentEvidence"][0]["bendRadius"] == 25
    assert report["endpointTable"][1]["id"] == "J2"
    assert report["collisionEvidence"][0]["status"] == "pass"
    assert report["supportEvidence"][0]["required"] == 0
    assert report["routingBom"][0]["totalLength"] == 50
    assert report["nativePreflight"]["readyForNativeWrite"] is False


def test_routing_report_blocks_missing_endpoint_reference(monkeypatch):
    """@brief 不存在的端点引用必须阻断，不能生成假路线。"""
    monkeypatch.setattr(routing_review, "probe_solidworks_routing", lambda: {"status": "blocked", "readyForNativeWrite": False})
    report = routing_review.build_routing_report({
        "routeType": "pipe",
        "minimumBendRadius": 30,
        "endpoints": [
            {"id": "P1", "position": [0, 0, 0]},
            {"id": "P2", "position": [100, 0, 0]},
        ],
        "segments": [{"id": "S1", "start": "P1", "end": "missing", "bendRadius": 30}],
    })

    assert report["status"] == "blocked"
    assert report["error_code"] == "routing_document_invalid"
    assert any(item["code"] == "routing_endpoint_reference_missing" for item in report["reviewFindings"])


def test_routing_report_detects_clearance_collision_and_support_gap(monkeypatch):
    """@brief 穿越障碍物或支撑不足必须形成结构化复核证据。"""
    monkeypatch.setattr(routing_review, "probe_solidworks_routing", lambda: {"status": "blocked", "readyForNativeWrite": False})
    report = routing_review.build_routing_report({
        "routeType": "hydraulic",
        "minimumBendRadius": 40,
        "minimumClearance": 10,
        "maximumSupportSpacing": 50,
        "endpoints": [
            {"id": "A", "position": [0, 0, 0]},
            {"id": "B", "position": [120, 0, 0]},
        ],
        "segments": [{"id": "P1", "start": "A", "end": "B", "bendRadius": 40, "diameter": 12}],
        "obstacles": [{"id": "FRAME", "min": [55, -5, -5], "max": [65, 5, 5]}],
        "supports": [{"id": "CLAMP-1", "segmentId": "P1", "distanceAlong": 40}],
    })

    assert report["status"] == "blocked"
    assert report["collisionEvidence"][0]["obstacles"] == ["FRAME"]
    assert report["supportEvidence"][0]["required"] == 2
    assert any(item["code"] == "routing_supports_insufficient" for item in report["reviewFindings"])


def test_routing_report_blocks_disconnected_subgraphs_and_orphan_support(monkeypatch):
    """@brief 所有端点均被引用也不能掩盖互不连通的路线网络。"""
    monkeypatch.setattr(routing_review, "probe_solidworks_routing", lambda: {"status": "blocked", "readyForNativeWrite": False})
    report = routing_review.build_routing_report({
        "routeType": "tube",
        "units": "mm",
        "minimumBendRadius": 10,
        "maximumSupportSpacing": 100,
        "endpoints": [
            {"id": "A", "position": [0, 0, 0]},
            {"id": "B", "position": [10, 0, 0]},
            {"id": "C", "position": [100, 0, 0]},
            {"id": "D", "position": [110, 0, 0]},
        ],
        "segments": [
            {"id": "S1", "start": "A", "end": "B", "bendRadius": 10},
            {"id": "S2", "start": "C", "end": "D", "bendRadius": 10},
        ],
        "supports": [{"id": "CLAMP-X", "segmentId": "MISSING", "distanceAlong": 1}],
    })
    codes = {item["code"] for item in report["reviewFindings"]}
    assert report["status"] == "blocked"
    assert "routing_disconnected_graph" in codes
    assert "routing_support_segment_missing" in codes


def test_routing_report_blocks_duplicate_support_and_zero_length_leg(monkeypatch):
    """@brief 重复支撑和路径重复点不能进入可复核状态。"""
    monkeypatch.setattr(routing_review, "probe_solidworks_routing", lambda: {"status": "blocked", "readyForNativeWrite": False})
    report = routing_review.build_routing_report({
        "routeType": "cable",
        "units": "mm",
        "minimumBendRadius": 10,
        "maximumSupportSpacing": 50,
        "endpoints": [{"id": "A", "position": [0, 0, 0]}, {"id": "B", "position": [100, 0, 0]}],
        "segments": [{"id": "S1", "start": "A", "end": "B", "bendRadius": 10, "points": [[0, 0, 0], [0, 0, 0], [100, 0, 0]]}],
        "supports": [
            {"id": "C1", "segmentId": "S1", "distanceAlong": 40},
            {"id": "C1", "segmentId": "S1", "distanceAlong": 80},
        ],
    })
    codes = {item["code"] for item in report["reviewFindings"]}
    assert report["status"] == "blocked"
    assert "routing_support_duplicate" in codes
    assert "routing_zero_length_leg" in codes


def test_routing_preflight_requires_registered_addin(monkeypatch, tmp_path):
    """@brief 类型库接口齐全但加载项未注册时仍必须 blocked。"""
    typelib = tmp_path / "SWRoutingLib.tlb"
    typelib.write_text("tlb", encoding="utf-8")
    monkeypatch.setattr(routing_review, "discover_installation", lambda _name: {"installed": True, "executable": str(tmp_path / "SLDWORKS.exe")})
    monkeypatch.setattr(routing_review, "_find_typelib", lambda _patterns: typelib)
    monkeypatch.setattr(routing_review, "missing_com_dependencies", lambda: [])
    monkeypatch.setattr(routing_review, "import_com_dependencies", lambda **_kwargs: (object(), None, None))
    monkeypatch.setattr(routing_review, "_type_names", lambda _pythoncom, _path: list(routing_review.ROUTING_INTERFACES))
    monkeypatch.setattr(routing_review, "_native_addin_registration", lambda: [])

    report = routing_review.probe_solidworks_routing()

    assert report["interfaceCoverage"] == 1.0
    assert report["readyForNativeWrite"] is False
    assert report["status"] == "blocked"
    assert report["error_code"] == "routing_addin_or_license_unavailable"
