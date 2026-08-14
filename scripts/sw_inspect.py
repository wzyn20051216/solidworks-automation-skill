"""
SolidWorks 测量与装配检查原语
零件整体尺寸（临时工程图 GetOutline@1:1）、包围盒、装配组件计数、特征/尺寸枚举。
能力清单：measurement_and_inspection=pilot。只读；不改、不保存被测文档（临时测量图除外）。
"""
import os

try:
    from .sw_connect import get_com_member, open_document, new_document
    from .sw_drawing import force_view_scale
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member, open_document, new_document
    from sw_drawing import force_view_scale
    from sw_preflight import import_com_dependencies

pythoncom, _win32com, VARIANT = import_com_dependencies()


class InspectionError(RuntimeError):
    """测量与装配检查错误。"""


def _basename_no_ext(path):
    """@brief 模型文件路径 -> 去扩展名的零件名（GetPathName 计数用）。"""
    if not path:
        return "?"
    name = os.path.basename(path)
    low = name.lower()
    for ext in (".sldprt", ".sldasm", ".slddrw"):
        if low.endswith(ext):
            return name[: -len(ext)]
    return os.path.splitext(name)[0]


def overall_dimensions(sw, part_path, *, close_part=True):
    """@brief 零件整体 W/H/D（mm），用临时工程图前+俯视图 GetOutline@1:1 测量。

    前视图给 W(X)×H(Y)，俯视图给 W(X)×D(Y)；W 取两视图平均。临时图测完即关（不保存）。
    类型化视图恒可用 GetOutline，对未类型化 OpenDoc6 文档上 GetBox 不可解析时仍可靠。

    返回 {status∈pass|review_required|failed, width_mm, height_mm, depth_mm,
    method, outline_front, outline_top, manual_review_required}。整体尺寸为视图轮廓含
    余量近似（1:1 下约 +6mm 余量），非严格名义尺寸。
    """
    result = {
        "status": "failed",
        "stage": "overall_dimensions",
        "width_mm": None,
        "height_mm": None,
        "depth_mm": None,
        "method": "throwaway_drawing_getoutline_at_1to1",
        "outline_front": None,
        "outline_top": None,
        "manual_review_required": True,
        "error_code": None,
        "retryable": False,
        "limitations": ["视图轮廓含约 6mm 余量，为近似值非严格名义尺寸"],
    }
    part_path = os.path.abspath(part_path)
    pre_open = None
    drawing = None
    opened_part_title = None
    try:
        try:
            pre_open = get_com_member(sw, "GetOpenDocumentByName", part_path)
        except Exception:
            pre_open = None
        # CreateDrawViewFromModelView3 需要零件已加载进会话
        if pre_open is None:
            open_document(sw, part_path, silent=True)
            opened_part_title = os.path.basename(part_path)
        drawing = new_document(sw, "drawing")
        if drawing is None:
            result["error_code"] = "MEASURE_NO_DRAWING"
            return result

        front = get_com_member(drawing, "CreateDrawViewFromModelView3", part_path, "*Front", 0.15, 0.20, 1.0)
        top = get_com_member(drawing, "CreateDrawViewFromModelView3", part_path, "*Top", 0.15, 0.08, 1.0)
        if not front or not top:
            result["error_code"] = "MEASURE_NO_VIEWS"
            return result
        # 强制 1:1：CreateDrawViewFromModelView3 的 Scale 被 UseSheetScale 忽略
        for vw in (front, top):
            force_view_scale(vw, 1.0, drawing_model=drawing)
        try:
            get_com_member(drawing, "EditRebuild3")
        except Exception:
            pass

        fo = list(get_com_member(front, "GetOutline"))
        to = list(get_com_member(top, "GetOutline"))
        if len(fo) < 4 or len(to) < 4:
            result["error_code"] = "MEASURE_NO_OUTLINE"
            return result
        fo = [float(v) for v in fo]
        to = [float(v) for v in to]
        result["outline_front"] = fo
        result["outline_top"] = to
        fw = (fo[2] - fo[0]) * 1000.0
        fh = (fo[3] - fo[1]) * 1000.0
        tw = (to[2] - to[0]) * 1000.0
        td = (to[3] - to[1]) * 1000.0
        result["width_mm"] = (fw + tw) / 2.0
        result["height_mm"] = fh
        result["depth_mm"] = td
        result["status"] = "pass"
    except Exception as exc:
        result["error_code"] = "MEASURE_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    finally:
        # 关闭临时工程图（不保存）
        if drawing is not None:
            try:
                title = get_com_member(drawing, "GetTitle")
                get_com_member(sw, "CloseDoc", title)
            except Exception:
                pass
        # 仅关闭本次新打开的零件；调用前已打开的保留
        if close_part and opened_part_title and pre_open is None:
            try:
                get_com_member(sw, "CloseDoc", opened_part_title)
            except Exception:
                pass
    return result


def bounding_box(model):
    """@brief 实体包围盒（mm）：GetBox(0)；不可解析时回退 GetBodies2+GetBodyBox 取并集。

    model: 类型化文档（open_document 结果）。未类型化派发上 GetBox 可能不可解析 ->
    回退到各实体 GetBodyBox 并集；仍失败返回 review_required（建议改用 overall_dimensions）。
    零件可能非原点对称，必须读 min/max。
    返回 {status, size_mm:[dx,dy,dz], range_mm:[xmin,ymin,zmin,xmax,ymax,zmax], method}。
    """
    result = {
        "status": "failed",
        "stage": "bounding_box",
        "size_mm": None,
        "range_mm": None,
        "method": None,
        "manual_review_required": True,
        "error_code": None,
        "retryable": False,
    }
    try:
        if model is None:
            result["error_code"] = "BBOX_NO_MODEL"
            return result
        box = None
        try:
            box = get_com_member(model, "GetBox", 0)
        except Exception:
            box = None
        if box and len(box) >= 6:
            box = [float(v) for v in box]
            xs, ys, zs = [box[0], box[3]], [box[1], box[4]], [box[2], box[5]]
            result["range_mm"] = [
                min(xs) * 1000.0, min(ys) * 1000.0, min(zs) * 1000.0,
                max(xs) * 1000.0, max(ys) * 1000.0, max(zs) * 1000.0,
            ]
            result["size_mm"] = [
                (max(xs) - min(xs)) * 1000.0,
                (max(ys) - min(ys)) * 1000.0,
                (max(zs) - min(zs)) * 1000.0,
            ]
            result["method"] = "GetBox(0)"
            result["status"] = "pass"
            return result

        # 回退：遍历实体 GetBodyBox 取并集
        bodies = None
        try:
            bodies = get_com_member(model, "GetBodies2", 0, False)
        except Exception:
            bodies = None
        if bodies:
            mins = [float("inf")] * 3
            maxs = [float("-inf")] * 3
            ok = False
            for body in bodies:
                bb = None
                try:
                    bb = get_com_member(body, "GetBodyBox")
                except Exception:
                    bb = None
                if not bb or len(bb) < 6:
                    continue
                bb = [float(v) for v in bb]
                for i in range(3):
                    mins[i] = min(mins[i], bb[i])
                    maxs[i] = max(maxs[i], bb[i + 3])
                ok = True
            if ok:
                result["range_mm"] = [
                    mins[0] * 1000.0, mins[1] * 1000.0, mins[2] * 1000.0,
                    maxs[0] * 1000.0, maxs[1] * 1000.0, maxs[2] * 1000.0,
                ]
                result["size_mm"] = [(maxs[i] - mins[i]) * 1000.0 for i in range(3)]
                result["method"] = "GetBodies2+GetBodyBox"
                result["status"] = "pass"
                return result

        result["status"] = "review_required"
        result["error_code"] = "BBOX_UNRESOLVABLE"
        result["limitations"] = ["GetBox/GetBodyBox 均不可解析，建议改用 overall_dimensions（临时图法）"]
    except Exception as exc:
        result["error_code"] = "BBOX_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result


def count_components(assembly_model, flat=True):
    """@brief 装配体组件计数（按零件名 basename 去重计数）。

    assembly_model: 已打开的装配体文档。flat=True 扁平（所有实例，含子装配内件，适合采购
    数量）；False 仅顶层（看结构）。用 IComponent2.GetPathName()（真方法）取路径，不用
    Name2 属性（动态派发下被当方法会返回访问器对象，破坏计数）。
    返回 {status∈pass|review_required|failed, counts:{name:n}, total, flat}。
    """
    result = {
        "status": "failed",
        "stage": "count_components",
        "counts": {},
        "total": 0,
        "flat": bool(flat),
        "manual_review_required": False,
        "error_code": None,
        "retryable": False,
    }
    try:
        if assembly_model is None:
            result["error_code"] = "COUNT_NO_MODEL"
            return result
        comps = get_com_member(assembly_model, "GetComponents", bool(flat))
        comps = list(comps) if comps else []
        tally = {}
        for comp in comps:
            path = None
            try:
                path = get_com_member(comp, "GetPathName")
            except Exception:
                path = None
            name = _basename_no_ext(path)
            tally[name] = tally.get(name, 0) + 1
        result["counts"] = tally
        result["total"] = sum(tally.values())
        result["status"] = "pass" if tally else "review_required"
        if not tally:
            result["error_code"] = "COUNT_EMPTY"
    except Exception as exc:
        result["error_code"] = "COUNT_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result


def enumerate_features(model, max_features=200):
    """@brief 枚举特征及驱动尺寸（只读）。

    GetFirstFeature→GetNextFeature 链；feat.Name(属性)、GetTypeName2()(方法)、
    GetDimensions()→FullName/SystemValue(属性，SystemValue 单位米->换算 mm)。
    返回 {status, features:[{index, name, type, dimensions:[{name, value_mm}]}],
    count, truncated}。max_features 限制枚举数；超出 truncated=True。
    """
    result = {
        "status": "failed",
        "stage": "enumerate_features",
        "features": [],
        "count": 0,
        "truncated": False,
        "manual_review_required": False,
        "error_code": None,
        "retryable": False,
    }
    try:
        if model is None:
            result["error_code"] = "FEAT_NO_MODEL"
            return result
        feat = get_com_member(model, "GetFirstFeature")
        idx = 0
        while feat is not None and idx < int(max_features):
            entry = {"index": idx, "name": "", "type": "", "dimensions": []}
            try:
                entry["name"] = str(get_com_member(feat, "Name"))
            except Exception:
                entry["name"] = ""
            try:
                entry["type"] = str(get_com_member(feat, "GetTypeName2"))
            except Exception:
                entry["type"] = ""
            try:
                dims = get_com_member(feat, "GetDimensions")
                for dim in (dims or []):
                    try:
                        full = str(get_com_member(dim, "FullName"))
                    except Exception:
                        full = ""
                    try:
                        val_mm = float(get_com_member(dim, "SystemValue")) * 1000.0
                    except Exception:
                        val_mm = None
                    entry["dimensions"].append({"name": full, "value_mm": val_mm})
            except Exception:
                pass
            result["features"].append(entry)
            idx += 1
            try:
                feat = get_com_member(feat, "GetNextFeature")
            except Exception:
                feat = None
        result["truncated"] = feat is not None  # 仍有未枚举特征
        result["count"] = idx
        result["status"] = "pass"
    except Exception as exc:
        result["error_code"] = "FEAT_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result
