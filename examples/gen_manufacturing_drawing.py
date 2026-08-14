"""
示例: 生成带尺寸 + GB/T 1804-m 公差的加工工程图
对**无模型驱动尺寸**的零件（导入件 / 占位件 / 只含拉伸参数件）做坐标扫描式标注，
并按 GB/T 1804-m 通用公差自动套对称 ±。

演示新增封装端到端：
  force_view_scale / pickability_ok / scan_view_dimensions（含 apply_gb1804m）
  + 文档级显示偏好（第一角 / 毫米 / 小数位，须在建视图前设）+ 存盘后扫描 + PDF 导出。

修改下方 PART_PATH / 名义尺寸 / 比例后即可对自制件复用。
"""
import os
import sys

sys.path.insert(0, r"../scripts")

from sw_connect import connect_solidworks, new_document, open_document, get_com_member
from sw_drawing import (
    add_view,
    force_view_scale,
    pickability_ok,
    scan_view_dimensions,
    export_sheet_to_pdf,
)

# ===== 配置（按你的零件改） =====
PART_PATH = r"C:\parts\mypart.sldprt"
DRAWING_PATH = r"C:\exports\mypart.SLDDRW"
PDF_PATH = r"C:\exports\mypart.pdf"
# 名义尺寸（mm）：仅用于 GB/T 1804-m 公差分档，不必精确到视图轮廓
NOMINAL_WIDTH_MM = 80.0
NOMINAL_HEIGHT_MM = 60.0
NOMINAL_DEPTH_MM = 40.0
SCALE = 1.0            # 视图比例；≥0.5 才可点选边/面，大件至少 0.5（1:2）
FRONT_X, FRONT_Y = 0.15, 0.20   # 前视图放置位置（米）
TOP_X, TOP_Y = 0.15, 0.08       # 俯视图位置（前视图下方）


def main():
    if not os.path.exists(PART_PATH):
        print("零件不存在: %s（改 PART_PATH 后重试）" % PART_PATH)
        return

    sw, _ = connect_solidworks()

    # 零件须先加载进会话，CreateDrawViewFromModelView3 才能引用
    open_document(sw, PART_PATH, silent=True)

    drawing = new_document(sw, "drawing")

    # 文档级显示偏好：必须在创建视图/尺寸【之前】设（显示样式创建即锁定）。
    # 整数为 SW2024 实证值；跨版本/语言按 references/api-lookup.md 查证枚举。
    get_com_member(drawing, "SetUserPreferenceIntegerValue", 79, 1)    # 第一角投影
    get_com_member(drawing, "SetUserPreferenceIntegerValue", 263, 5)   # 单位制 MMGS（毫米）
    get_com_member(drawing, "SetUserPreferenceIntegerValue", 49, 0)    # 线性尺寸小数位 = 0

    # 前视图 + 俯视图（比例由 force_view_scale 强制；add_view 的 scale 占位即可）
    front = add_view(drawing, PART_PATH, "*Front", FRONT_X, FRONT_Y)
    top = add_view(drawing, PART_PATH, "*Top", TOP_X, TOP_Y)

    # 强制真实比例（Scale 参数被 UseSheetScale 忽略）+ 可选择性门禁（≥1:2）
    for name, vw in (("Front", front), ("Top", top)):
        fr = force_view_scale(vw, SCALE, drawing_model=drawing)
        pk = pickability_ok(vw)
        print("  视图 %s: 强制=%s 比例=%s 可选=%s" % (name, fr["status"], pk.get("scale"), pk["status"]))
        if pk["status"] != "pass":
            print("    ! 比例 %s < 1:2，点选不可用：%s" % (pk.get("scale"), pk.get("reason")))
            print("    ! 请提升 SCALE 或换 A2 图幅再放可选比例。")

    # 新建视图仅暴露部分剪影边 —— 存盘后全部边线才可点选
    get_com_member(drawing, "SaveAs3", DRAWING_PATH, 0, 0)
    # SelectByID2 作用于活动文档：new_document 返回的 drawing 已是活动文档；
    # 多文档场景（同时还开着别的工程图）扫描前须 sw.ActivateDoc3(DRAWING_PATH, ...)

    # 坐标扫描式标注 W/H/D，自动套 GB/T 1804-m 对称公差
    report = scan_view_dimensions(
        drawing, front, top,
        nominal_width_mm=NOMINAL_WIDTH_MM,
        nominal_height_mm=NOMINAL_HEIGHT_MM,
        nominal_depth_mm=NOMINAL_DEPTH_MM,
        apply_tolerance=True,
    )
    print("扫描标注: %s" % report["status"])
    for d in report.get("dimensions", []):
        tr = d.get("tolerance_report") or {}
        print("  %s: set=%s 公差=%s/%s (type=%s)" % (
            d["axis"], d.get("display_dimension_set"),
            tr.get("plus_mm"), tr.get("minus_mm"), tr.get("tolerance_type")))
    if report["status"] != "pass":
        print("  ! 部分边线未定位: %s —— 须目视补标" % report.get("error_code"))

    # 重建 + 保存 + 导出 PDF
    get_com_member(drawing, "EditRebuild3")
    get_com_member(drawing, "Save")
    export_sheet_to_pdf(drawing, PDF_PATH)
    print("完成: %s / %s" % (DRAWING_PATH, PDF_PATH))


if __name__ == "__main__":
    main()
