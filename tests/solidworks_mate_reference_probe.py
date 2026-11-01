"""只读探测改名副本中配合引用的持久 ID；不保存源文档。"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_assembly import iter_feature_tree
from scripts.sw_connect import get_com_member
from scripts.sw_rename_copy import _open_checked, _sha256
from scripts.sw_session import SolidWorksSession


def read(model):
    extension = get_com_member(model, "Extension")
    records = []
    for feature, _ in iter_feature_tree(model):
        kind = str(get_com_member(feature, "GetTypeName2") or "")
        if not kind.startswith("Mate") or kind == "MateGroup":
            continue
        mate = get_com_member(feature, "GetSpecificFeature2")
        for index in range(get_com_member(mate, "GetMateEntityCount")):
            item = get_com_member(mate, "MateEntity", index)
            component = get_com_member(item, "ReferenceComponent")
            ref = get_com_member(item, "Reference")
            owner = get_com_member(component, "GetModelDoc2")
            owner_extension = get_com_member(owner, "Extension")
            underlying = get_com_member(owner_extension, "GetCorresponding2", ref)
            if underlying is None:
                raise AssertionError("无法解析配合在组件文档中的对象")
            identity = get_com_member(owner_extension, "GetPersistReference3", underlying)
            print("native types", type(identity).__name__, "component id", get_com_member(component, "GetID"), "parameter type", type(get_com_member(item, "EntityParams")).__name__, flush=True)
            print("reference", get_com_member(feature, "Name"), index,
                  get_com_member(component, "GetPathName"), get_com_member(item, "ReferenceType2"),
                  get_com_member(item, "EntityParams"), "persist len", len(identity or ()), flush=True)
            if not identity:
                raise AssertionError("配合几何引用不支持持久 ID")
            records.append((identity, owner_extension))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("copy", type=Path)
    args = parser.parse_args()
    hashes = {p: _sha256(p) for p in (args.source, args.copy)}
    with SolidWorksSession(version=2026, visible=True) as session:
        model = _open_checked(session, args.source)
        before = read(model)
        session.close(model=model)
        model = _open_checked(session, args.copy)
        after = read(model)
        assert len(before) == len(after) and before
        extension = get_com_member(model, "Extension")
        extension._FlagAsMethod("IsSamePersistentID")
        for (a, _), (b, ext) in zip(before, after):
            ext._FlagAsMethod("IsSamePersistentID")
            status = ext.IsSamePersistentID(a, b)
            print("persistent identity", status, flush=True)
            assert status == 1
    assert all(_sha256(p) == value for p, value in hashes.items())


if __name__ == "__main__":
    main()
