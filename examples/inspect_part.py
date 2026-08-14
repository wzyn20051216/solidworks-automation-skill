"""
示例: 零件 / 装配体检查
读取质量属性、整体尺寸、包围盒、装配组件计数、特征枚举。
全部只读，不改、不保存被测文档（临时测量图测完即关）。

演示新增封装：mass_properties / overall_dimensions / bounding_box /
count_components / enumerate_features。修改下方路径后即可复用。
"""
import os
import sys

sys.path.insert(0, r"../scripts")

from sw_connect import connect_solidworks, open_document
from sw_mass_properties import mass_properties
from sw_inspect import (
    overall_dimensions,
    bounding_box,
    count_components,
    enumerate_features,
)

PART_PATH = r"C:\parts\mypart.sldprt"
ASSEMBLY_PATH = r"C:\parts\myassembly.sldasm"


def main():
    sw, _ = connect_solidworks()

    if os.path.exists(PART_PATH):
        print("=== 零件: %s ===" % os.path.basename(PART_PATH))
        model = open_document(sw, PART_PATH, silent=True)

        mp = mass_properties(model)
        print("质量属性: status=%s 材料=%s" % (mp["status"], mp.get("material") or "(未设)"))
        if mp.get("volume_mm3") is not None:
            print("  体积=%.1f mm³  表面积=%.1f mm²" % (mp["volume_mm3"], mp["surface_mm2"]))
        if mp["mass_meaningful"]:
            print("  质量=%.4f kg  重心(mm)=%s" % (mp["mass_kg"], mp["center_of_mass_mm"]))
        else:
            print("  质量=%s kg（材料/密度未设，须人工指定）" % mp.get("mass_kg"))

        # overall_dimensions 内部自行开零件；此处已打开则复用、不重复关
        od = overall_dimensions(sw, PART_PATH, close_part=False)
        print("整体尺寸: W=%s H=%s D=%s mm (status=%s，含~6mm 余量近似)" % (
            od["width_mm"], od["height_mm"], od["depth_mm"], od["status"]))

        bb = bounding_box(model)
        print("包围盒: size(mm)=%s via %s" % (bb["size_mm"], bb["method"]))

        feats = enumerate_features(model, max_features=20)
        print("特征(%d%s):" % (feats["count"], "..." if feats["truncated"] else ""))
        for f in feats["features"][:5]:
            dims = ", ".join("%s=%.3f" % (d["name"], d["value_mm"])
                             for d in f["dimensions"] if d.get("value_mm") is not None)
            print("  [%d] %s (%s)%s" % (f["index"], f["name"], f["type"], ("  " + dims) if dims else ""))

    if os.path.exists(ASSEMBLY_PATH):
        print("\n=== 装配体: %s ===" % os.path.basename(ASSEMBLY_PATH))
        asm = open_document(sw, ASSEMBLY_PATH, silent=True)
        cc = count_components(asm, flat=True)
        print("组件计数(flat): total=%s status=%s" % (cc["total"], cc["status"]))
        for name, n in sorted(cc["counts"].items(), key=lambda kv: -kv[1]):
            print("  %s ×%d" % (name, n))


if __name__ == "__main__":
    main()
