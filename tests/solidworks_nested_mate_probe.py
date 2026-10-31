"""在临时目录创建带配合的两层装配体并探索副本引用替换。"""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_assembly import add_component, add_mate5_checked, get_component_feature_entity, select_entities_for_mate, collect_mate_feature_summary, iter_feature_tree
from scripts.sw_connect import get_com_member
from scripts.sw_part import sketch, sketch_rectangle, extrude_boss
from scripts.sw_rename_copy import _sha256
from scripts.sw_session import SolidWorksSession
from scripts.sw_review import _feature_health


def mate_health(model):
    return [{"name": get_com_member(feature, "Name"), "type": get_com_member(feature, "GetTypeName2"),
             **_feature_health(feature)} for feature, _ in iter_feature_tree(model)
            if str(get_com_member(feature, "GetTypeName2") or "").startswith("Mate")
            and get_com_member(feature, "GetTypeName2") != "MateGroup"]


def main():
    root = Path(tempfile.mkdtemp(prefix="sw_nested_mate_probe_"))
    src, dst = root / "source", root / "copy"
    src.mkdir()
    dst.mkdir()
    with SolidWorksSession(version=2026, visible=True) as session:
        paths = []
        for index in range(2):
            model = session.new_part()
            with sketch(model, "Front Plane") as ref:
                sketch_rectangle(model, 0, 0, .02 + index * .01, .01)
            if not extrude_boss(model, ref, .005):
                raise RuntimeError("零件拉伸失败")
            path = src / f"{root.name}_part{index}.sldprt"
            if not session.save(model, str(path)):
                raise RuntimeError("零件保存失败")
            session.close(model=model)
            paths.append(path)
        for path in paths:
            session.open(str(path), read_only=True, silent=True)
        sub = session.new_assembly()
        subpath = src / f"{root.name}_sub.sldasm"
        if not session.save(sub, str(subpath)):
            raise RuntimeError("初始子装配体保存失败")
        print("sub title", get_com_member(sub, "GetTitle"), "path", get_com_member(sub, "GetPathName"), flush=True)
        comps = [add_component(sub, str(path), x=index * .04, sw=session.sw) for index, path in enumerate(paths)]
        if not all(comps):
            raise RuntimeError("子装配体组件添加失败")
        entities = [get_component_feature_entity(c, ["Front Plane", "前视基准面"]) for c in comps]
        select_entities_for_mate(sub, *entities)
        if not add_mate5_checked(sub, 0, name="probe_coincident"):
            raise RuntimeError("创建配合失败")
        sub.ForceRebuild3(False)
        print("source mates", collect_mate_feature_summary(sub), flush=True)
        original_mate_health = mate_health(sub)
        if not original_mate_health or any(item["health_status"] != "healthy" for item in original_mate_health):
            raise AssertionError(f"源配合状态异常: {original_mate_health}")
        if not session.save(sub, str(subpath)):
            raise RuntimeError("子装配体保存失败")
        session.close(model=sub)
        session.open(str(subpath), read_only=True, silent=True)
        top = session.new_assembly()
        top_path = src / f"{root.name}_top.sldasm"
        if not session.save(top, str(top_path)):
            raise RuntimeError("初始顶层装配体保存失败")
        if not add_component(top, str(subpath), sw=session.sw):
            raise RuntimeError("顶层插入子装配体失败")
        if not session.save(top, str(top_path)):
            raise RuntimeError("顶层装配体保存失败")
        print("top dependencies", get_com_member(top, "GetDependencies2", False, True, False), flush=True)
        session.close(model=top)
        hashes = {path: _sha256(path) for path in [*paths, subpath, top_path]}
        copies = {path: dst / ("copy_" + path.name) for path in hashes}
        for old, new in copies.items():
            shutil.copyfile(old, new)
        for old in paths:
            if not session.sw.ReplaceReferencedDocument(str(copies[subpath]), str(old), str(copies[old])):
                raise RuntimeError("子装配体引用替换失败")
        if not session.sw.ReplaceReferencedDocument(str(copies[top_path]), str(subpath), str(copies[subpath])):
            raise RuntimeError("顶层装配体引用替换失败")
        reopened = session.open(str(copies[top_path]), read_only=True, silent=True)
        components = get_com_member(reopened, "GetComponents", False) or []
        actual = {str(get_com_member(c, "GetPathName") or "").casefold() for c in components}
        expected = {str(copies[p]).casefold() for p in [subpath, *paths]}
        if actual != expected:
            raise AssertionError(f"嵌套引用不一致: {actual} != {expected}")
        sub_component = next(c for c in components if str(get_com_member(c, "GetPathName") or "").casefold() == str(copies[subpath]).casefold())
        copied_sub = get_com_member(sub_component, "GetModelDoc2")
        mates = collect_mate_feature_summary(copied_sub)
        print("copy mates", mates, flush=True)
        copied_health = mate_health(copied_sub)
        print("mate health", original_mate_health, copied_health, flush=True)
        if copied_health != original_mate_health:
            raise AssertionError("改名后配合健康状态不一致")
        if not any(row["type"] == "MateCoincident" for row in mates):
            raise AssertionError("重开后未找到重合配合")
        if any(_sha256(path) != digest for path, digest in hashes.items()):
            raise AssertionError("源文件发生变化")
        print("probe directory", root, flush=True)


if __name__ == "__main__":
    main()
