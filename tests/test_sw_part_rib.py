"""筋的调用签名和VOID返回契约；离线替身不代表CAD几何验证。"""
import pytest

from scripts import sw_part


class Feature:
    def __init__(self, name, kind="Rib"):
        self.Name = name
        self.kind = kind
        self.next = None

    def GetTypeName2(self):
        return self.kind

    def GetNextFeature(self):
        return self.next


class Model:
    def __init__(self, before=(), added=()):
        self.features = list(before)
        self.added = added
        self.calls = []
        self.FeatureManager = self
        self._link()

    def _link(self):
        for i, feature in enumerate(self.features):
            feature.next = self.features[i + 1] if i + 1 < len(self.features) else None

    def FirstFeature(self):
        return self.features[0] if self.features else None

    def InsertRib(self, Is2Sided, ReverseThicknessDir, Thickness,
                  ReferenceEdgeIndex, ReverseMaterialDir, IsDrafted,
                  DraftOutward, DraftAngle, IsNormToSketch, IsDraftedFromWall):
        self.calls.append((Is2Sided, ReverseThicknessDir, Thickness,
                           ReferenceEdgeIndex, ReverseMaterialDir, IsDrafted,
                           DraftOutward, DraftAngle, IsNormToSketch, IsDraftedFromWall))
        self.features.extend(self.added)
        self._link()
        return None


@pytest.mark.parametrize("direction", [True, False])
def test_complete_signature_preserves_legacy_two_sided_flag_and_reads_void_result(monkeypatch, direction):
    created = Feature("Rib2")
    model = Model([Feature("Rib1")], [created])
    selections = []
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda *args: selections.append(args))
    assert sw_part.rib(model, "profile", .006, direction=direction) is created
    assert selections == [(model, "profile")]
    assert model.calls == [(direction, False, .006, 0, False, False, False, 0, False, False)]


def test_default_flag_and_new_rib_are_not_confused_with_other_features(monkeypatch):
    created = Feature("Rib2")
    model = Model([Feature("Rib1")], [created, Feature("Folder", "HistoryFolder")])
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda *_: None)
    assert sw_part.rib(model, "profile", .006) is created
    assert model.calls[0][0] is True


def test_no_new_feature_does_not_return_an_existing_rib(monkeypatch):
    model = Model([Feature("Rib1")])
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda *_: None)
    assert sw_part.rib(model, "profile", .006) is None


def test_ambiguous_new_ribs_are_not_reported_as_one_result(monkeypatch):
    model = Model(added=[Feature("Rib1"), Feature("Rib2")])
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda *_: None)
    with pytest.raises(RuntimeError, match="新增多个筋特征"):
        sw_part.rib(model, "profile", .006)
