"""
示例 2: 创建复杂零件
演示草图约束、多个特征、倒角和圆角
"""
import sys
sys.path.insert(0, r"../scripts")

from sw_connect import connect_solidworks, mm, new_document
from sw_part import (
    start_sketch, sketch_rectangle, sketch_circle, end_sketch,
    extrude_boss, extrude_cut, fillet, chamfer
)

def main():
    sw, _ = connect_solidworks()
    model = new_document(sw, "part")

    # 1. 创建基体
    print("创建基体...")
    start_sketch(model, "Front Plane")
    sketch_rectangle(model, 0, 0, mm(80), mm(60))
    end_sketch(model)
    extrude_boss(model, "Sketch1", mm(20))

    # 2. 在顶面创建孔
    print("创建孔...")
    # 选择顶面并开始草图
    model.Extension.SelectByID2("", "FACE", 0, 0, mm(20), False, 0, None, 0)
    model.SketchManager.InsertSketch(True)

    # 绘制 4 个孔
    positions = [
        (mm(20), mm(15)),
        (mm(60), mm(15)),
        (mm(20), mm(45)),
        (mm(60), mm(45))
    ]
    for x, y in positions:
        sketch_circle(model, x, y, mm(5))

    end_sketch(model)
    extrude_cut(model, "Sketch2", 0)  # 0 = 完全贯穿

    # 3. 添加倒角和圆角
    print("添加倒角和圆角...")
    # 选择底部边线添加倒角
    model.Extension.SelectByID2("", "EDGE", 0, 0, 0, False, 0, None, 0)
    chamfer(model, mm(2), 45)

    # 选择顶部边线添加圆角
    model.Extension.SelectByID2("", "EDGE", 0, 0, mm(20), False, 0, None, 0)
    fillet(model, mm(3))

    print("复杂零件创建完成!")

if __name__ == "__main__":
    main()
