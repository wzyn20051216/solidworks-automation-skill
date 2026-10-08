"""@brief 基准居中安装板，四孔有定位驱动尺寸，保存后复核实际草图状态。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import mm
from scripts.sw_session import SolidWorksSession
from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, extrude_boss, extrude_cut
from scripts.sw_sketch_quality import fully_define_sketch, inspect_model_sketches


def main():
    """@brief 80×60×20 板，四个直径 10 的孔中心位于 ±20、±15 毫米。"""
    with SolidWorksSession() as session:
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_rectangle(model, 0, 0, mm(80), mm(60))
            fully_define_sketch(model)
        if extrude_boss(model, ref, mm(20), direction=False) is None:
            raise RuntimeError("安装板基体失败")
        with sketch(model, "Front Plane") as ref:
            for x, y in ((-20, -15), (20, -15), (-20, 15), (20, 15)):
                sketch_circle(model, mm(x), mm(y), mm(5))
            fully_define_sketch(model)
        if extrude_cut(model, ref, 0, direction=True) is None:
            raise RuntimeError("四孔切除失败")
        path = Path.home() / "cad-output" / "plate.sldprt"
        if not session.save(model, str(path)):
            raise RuntimeError("保存失败")
        print({"output": str(path), "sketch_quality": inspect_model_sketches(model)})


if __name__ == "__main__":
    main()
