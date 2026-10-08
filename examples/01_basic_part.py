"""@brief 创建有真实驱动尺寸的圆柱，保存并复核后清理本轮文档。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import mm
from scripts.sw_session import SolidWorksSession
from scripts.sw_part import sketch, sketch_circle, extrude_boss
from scripts.sw_sketch_quality import fully_define_sketch, inspect_model_sketches


def main():
    """@brief 以原点为圆心生成可编辑的基础零件。"""
    with SolidWorksSession() as session:
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_circle(model, 0, 0, mm(25))
            fully_define_sketch(model)
        if extrude_boss(model, ref, mm(50)) is None:
            raise RuntimeError("圆柱拉伸失败")
        path = Path.home() / "cad-output" / "cylinder.sldprt"
        if not session.save(model, str(path)):
            raise RuntimeError("保存失败")
        print({"output": str(path), "sketch_quality": inspect_model_sketches(model)})


if __name__ == "__main__":
    main()
