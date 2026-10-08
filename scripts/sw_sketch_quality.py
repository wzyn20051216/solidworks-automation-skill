"""@brief 草图质量适配：回读约束、尺寸与 Fix，不把 API 返回值当验收。"""
try:
    from .sw_connect import create_empty_dispatch_variant, get_com_member
except ImportError:
    from sw_connect import create_empty_dispatch_variant, get_com_member


def inspect_sketch(sketch):
    """@brief 读取可编辑性证据；信息无法取得时保持 blocked。
    @param sketch ISketch 对象。
    @return 约束状态、驱动尺寸/关系数量与固定关系数量。
    """
    record = {"status": "blocked", "constrained_status": None, "dimension_count": None,
              "relation_count": None, "fix_count": None, "dimension_names": [], "errors": []}
    try:
        record["constrained_status"] = int(get_com_member(sketch, "GetConstrainedStatus"))
        relations = list(get_com_member(get_com_member(sketch, "RelationManager"), "GetRelations", 0) or [])
        record["relation_count"] = len(relations)
        record["fix_count"] = sum(int(get_com_member(item, "GetRelationType")) in {17, 70, 74} for item in relations)
        names = set()
        for relation in relations:
            dimension = get_com_member(relation, "GetDisplayDimension")
            if dimension is not None:
                names.add(str(get_com_member(dimension, "GetNameForSelection")))
        record["dimension_names"] = sorted(names)
        record["dimension_count"] = len(names)
        record["status"] = "pass" if record["constrained_status"] == 3 and names and record["fix_count"] == 0 else "review_required"
    except Exception as error:
        record["errors"].append(str(error))
    return record


def fully_define_sketch(model):
    """@brief 以原点为尺寸基准补全草图，禁止用 Fix 代替设计参数。
    @param model 处于草图编辑态的 IModelDoc2。
    @return 实际回读证据；无法取得明确通过证据时抛出异常。
    """
    active = get_com_member(model.SketchManager, "ActiveSketch")
    if active is None:
        raise ValueError("完全定义必须在草图编辑态执行")
    model.ClearSelection2(True)
    try:
        # 原点特征在中英文界面有不同名称；先枚举真实特征名，再构造官方点引用。
        origins = ["Origin", "原点"]
        feature = get_com_member(model, "FirstFeature", default=None)
        while feature is not None:
            if str(get_com_member(feature, "GetTypeName2")) == "OriginProfileFeature":
                origins.insert(0, str(get_com_member(feature, "Name")))
                break
            feature = get_com_member(feature, "GetNextFeature")
        selected = False
        for origin in dict.fromkeys(origins):
            for point_name in ("Point1", "点1"):
                selected = model.Extension.SelectByID2(point_name + "@" + origin, "EXTSKETCHPOINT", 0, 0, 0, False, 6,
                    create_empty_dispatch_variant(), 0)
                if selected:
                    break
            if selected:
                break
        if not selected:
            raise RuntimeError("无法选择原点作为水平/垂直尺寸基准")
        # 1023 是已核对的十种关系组合，不包含固定关系。返回码未定义，必须回读。
        returned = model.SketchManager.FullyDefineSketch(True, True, 1023, True,
            1, create_empty_dispatch_variant(), 1, create_empty_dispatch_variant(), 1, 1)
        record = inspect_sketch(active)
        record["api_return"] = returned
        if record["status"] != "pass":
            raise RuntimeError(f"草图未通过完全定义与可编辑性验收: {record}")
        return record
    finally:
        model.ClearSelection2(True)


def inspect_model_sketches(model):
    """@brief 复用已有特征遍历，检查保存模型的全部建模草图。"""
    try:
        from .sw_assembly import iter_feature_tree
    except ImportError:
        from sw_assembly import iter_feature_tree
    records = []
    seen = set()
    for feature, _depth in iter_feature_tree(model):
        if str(get_com_member(feature, "GetTypeName2")) not in {"ProfileFeature", "3DProfileFeature"}:
            continue
        name = str(get_com_member(feature, "Name"))
        if name in seen:
            continue
        seen.add(name)
        record = inspect_sketch(get_com_member(feature, "GetSpecificFeature2"))
        record["name"] = name
        try:
            owner = get_com_member(feature, "GetOwnerFeature")
            children = list(get_com_member(feature, "GetChildren") or [])
            consumers = [owner] if owner is not None else children
            record["consumed_by"] = [str(get_com_member(item, "Name")) for item in consumers
                if str(get_com_member(item, "GetTypeName2")) not in {"ProfileFeature", "3DProfileFeature", "RefAxis", "RefPlane", "RefPoint"}]
            record["dangling"] = not bool(record["consumed_by"])
        except Exception as error:
            record["dangling"] = None
            record["errors"].append(str(error))
        if record["dangling"] is not False:
            record["status"] = "review_required"
        records.append(record)
    return {"status": "pass" if records and all(item["status"] == "pass" for item in records) else "review_required", "sketches": records}
