"""
示例 5: 创建工程图
演示如何创建工程图并添加视图、尺寸和 BOM 表
"""
import sys
sys.path.insert(0, r"../scripts")

from sw_connect import connect_solidworks, new_document
from sw_drawing import (
    create_standard_views,
    insert_dimensions,
    add_note,
    export_sheet_to_pdf
)

def main():
    sw, _ = connect_solidworks()

    # 创建新工程图
    print("创建工程图...")
    drawing = new_document(sw, "drawing")

    # 指定零件路径
    part_path = r"C:\parts\mypart.sldprt"

    # 创建标准三视图
    print("创建三视图...")
    create_standard_views(drawing, part_path)

    # 自动标注尺寸
    print("添加尺寸标注...")
    insert_dimensions(drawing)

    # 添加注释
    print("添加注释...")
    add_note(drawing, 0.1, 0.05, "材料: 钢 1045\n表面处理: 镀锌")

    # 导出为 PDF
    output_pdf = r"C:\exports\drawing.pdf"
    print(f"导出 PDF: {output_pdf}")
    export_sheet_to_pdf(drawing, output_pdf)

    print("工程图创建完成!")

if __name__ == "__main__":
    main()
