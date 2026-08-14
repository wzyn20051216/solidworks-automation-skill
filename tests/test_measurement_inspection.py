"""测量与装配检查原语无 COM 测试。

bounding_box / count_components / enumerate_features 用假文档直接测；
overall_dimensions 经 monkeypatch 注入假的 open_document / new_document /
force_view_scale，断言前+俯视图 GetOutline@1:1 的 W/H/D 换算。
"""
import scripts.sw_inspect as sw_inspect
from scripts.sw_inspect import (
    overall_dimensions,
    bounding_box,
    count_components,
    enumerate_features,
)


# ---- bounding_box ----

class _BoxModel:
    def __init__(self, box=None, bodies=None):
        self._box = box
        self._bodies = bodies

    def GetBox(self, arg):
        if self._box is None:
            raise RuntimeError("GetBox 不可解析（未类型化派发）")
        return self._box

    def GetBodies2(self, code, visible):
        return self._bodies


class _Body:
    def __init__(self, bb):
        self._bb = bb

    def GetBodyBox(self):
        return self._bb


def test_bounding_box_getbox_ok():
    # 100x100x150mm，原点对称（-0.05..0.05, -0.05..0.05, -0.075..0.075）米
    m = _BoxModel(box=[-0.05, -0.05, -0.075, 0.05, 0.05, 0.075])
    r = bounding_box(m)
    assert r["status"] == "pass"
    assert r["method"] == "GetBox(0)"
    assert r["size_mm"] == [100.0, 100.0, 150.0]
    assert r["range_mm"] == [-50.0, -50.0, -75.0, 50.0, 50.0, 75.0]


def test_bounding_box_non_origin_symmetric():
    # 非原点对称 -> 仍须读 min/max
    m = _BoxModel(box=[0.0, 0.0, 0.0, 0.100, 0.050, 0.150])
    r = bounding_box(m)
    assert r["status"] == "pass"
    assert r["size_mm"] == [100.0, 50.0, 150.0]
    assert r["range_mm"] == [0.0, 0.0, 0.0, 100.0, 50.0, 150.0]


def test_bounding_box_bodies_fallback():
    # GetBox 不可解析 -> 回退 GetBodies2 + GetBodyBox 取并集
    bodies = [
        _Body([0.0, 0.0, 0.0, 0.050, 0.050, 0.050]),
        _Body([0.050, 0.0, 0.0, 0.100, 0.050, 0.050]),
    ]
    m = _BoxModel(box=None, bodies=bodies)
    r = bounding_box(m)
    assert r["status"] == "pass"
    assert r["method"] == "GetBodies2+GetBodyBox"
    assert r["size_mm"] == [100.0, 50.0, 50.0]
    assert r["range_mm"] == [0.0, 0.0, 0.0, 100.0, 50.0, 50.0]


def test_bounding_box_unresolvable():
    m = _BoxModel(box=None, bodies=None)
    r = bounding_box(m)
    assert r["status"] == "review_required"
    assert r["error_code"] == "BBOX_UNRESOLVABLE"


# ---- count_components ----

class _Comp:
    def __init__(self, path):
        self._path = path

    def GetPathName(self):
        return self._path


class _Assembly:
    def __init__(self, comps):
        self._comps = comps

    def GetComponents(self, flat):
        return self._comps


def test_count_components_flat_tally():
    asm = _Assembly([
        _Comp(r"C:\lib\螺栓M8.sldprt"),
        _Comp(r"C:\lib\螺栓M8.sldprt"),
        _Comp(r"D:\motor\钻头M5.sldprt"),
    ])
    r = count_components(asm, flat=True)
    assert r["status"] == "pass"
    assert r["total"] == 3
    assert r["counts"] == {"螺栓M8": 2, "钻头M5": 1}
    assert r["flat"] is True


def test_count_components_empty_review():
    r = count_components(_Assembly([]), flat=True)
    assert r["status"] == "review_required"
    assert r["error_code"] == "COUNT_EMPTY"


# ---- enumerate_features ----

class _Dim:
    FullName = "D1@Sketch1"
    SystemValue = 0.080   # 米 -> 80mm


class _Feat:
    def __init__(self, name, ftype, dims, nxt=None):
        self.Name = name
        self._type = ftype
        self._dims = dims
        self._nxt = nxt

    def GetTypeName2(self):
        return self._type

    def GetDimensions(self):
        return self._dims

    def GetNextFeature(self):
        return self._nxt


class _FeatModel:
    def __init__(self, first):
        self._first = first

    def GetFirstFeature(self):
        return self._first


def test_enumerate_features_chain():
    f2 = _Feat("Boss-Extrude1", "Extrusion", [_Dim()], nxt=None)
    f1 = _Feat("Sketch1", "ProfileFeature", [], nxt=f2)
    r = enumerate_features(_FeatModel(f1), max_features=10)
    assert r["status"] == "pass"
    assert r["count"] == 2
    assert r["truncated"] is False
    assert r["features"][0]["name"] == "Sketch1"
    assert r["features"][1]["name"] == "Boss-Extrude1"
    assert r["features"][1]["dimensions"][0]["value_mm"] == 80.0


def test_enumerate_features_truncation():
    # 链长于 max_features -> truncated
    tail = _Feat("F3", "T", [], nxt=None)
    mid = _Feat("F2", "T", [], nxt=tail)
    head = _Feat("F1", "T", [], nxt=mid)
    r = enumerate_features(_FeatModel(head), max_features=2)
    assert r["count"] == 2
    assert r["truncated"] is True


# ---- overall_dimensions（monkeypatch 真实 open/new/force 依赖）----

class _OLView:
    def __init__(self, outline):
        self._ol = outline

    def GetOutline(self):
        return self._ol


class _ThrowawayDrawing:
    def __init__(self, front_ol, top_ol):
        self._front = front_ol
        self._top = top_ol
        self.created = []

    def CreateDrawViewFromModelView3(self, path, name, x, y, scale):
        self.created.append(name)
        return _OLView(self._front if name == "*Front" else self._top)

    def EditRebuild3(self):
        return True

    def GetTitle(self):
        return "throwaway.SLDDRW"


class _FakeSW:
    def __init__(self):
        self.closed = []

    def GetOpenDocumentByName(self, path):
        return None

    def CloseDoc(self, title):
        self.closed.append(title)
        return True


def test_overall_dimensions_from_outlines(monkeypatch):
    part = r"C:\tmp\block.sldprt"   # 不需真实文件：open_document 被 patch 不真读
    drawing = _ThrowawayDrawing(
        front_ol=[0.0, 0.0, 0.060, 0.010],   # W=60mm H=10mm
        top_ol=[0.0, 0.0, 0.060, 0.040],     # W=60mm D=40mm
    )
    monkeypatch.setattr(sw_inspect, "open_document", lambda sw, p, silent=False: object())
    monkeypatch.setattr(sw_inspect, "new_document", lambda sw, doc_type: drawing)
    monkeypatch.setattr(sw_inspect, "force_view_scale", lambda vw, s, drawing_model=None: {"status": "pass"})

    sw = _FakeSW()
    r = overall_dimensions(sw, str(part))
    assert r["status"] == "pass"
    assert abs(r["width_mm"] - 60.0) < 1e-6     # (60+60)/2
    assert abs(r["height_mm"] - 10.0) < 1e-6
    assert abs(r["depth_mm"] - 40.0) < 1e-6
    assert r["outline_front"] == [0.0, 0.0, 0.060, 0.010]
    assert set(drawing.created) == {"*Front", "*Top"}
    # 临时图与本次新开的零件都应被关闭
    assert "throwaway.SLDDRW" in sw.closed
    assert "block.sldprt" in sw.closed
