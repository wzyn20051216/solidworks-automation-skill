"""
示例 1: 创建基本零件
演示如何创建一个简单的圆柱体零件
"""
import sys
sys.path.insert(0, r"../scripts")

from sw_connect import connect_solidworks, mm, new_document, save_document
from sw_part import start_sketch, sketch_circle, end_sketch, extrude_boss

def main():
    # 连接 SolidWorks
    print("连接 SolidWorks...")
    sw, _ = connect_solidworks()

    # 创建新零件
    print("创建新零件...")
    model = new_document(sw, "part")

    # 在前视基准面上绘制圆
    print("绘制草图...")
    start_sketch(model, "Front Plane")
    sketch_circle(model, 0, 0, mm(25))  # 半径 25mm
    end_sketch(model)

    # 拉伸 50mm
    print("拉伸特征...")
    extrude_boss(model, "Sketch1", mm(50))

    # 保存文件
    output_path = r"C:\temp\cylinder.sldprt"
    print(f"保存零件到: {output_path}")
    save_document(model, output_path)

    print("完成!")

if __name__ == "__main__":
    main()
