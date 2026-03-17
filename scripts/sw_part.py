"""
SolidWorks 零件建模工具
提供草图绘制和特征创建的常用函数
"""
import win32com.client
import pythoncom
from win32com.client import VARIANT


# ============================================================
# 草图操作
# ============================================================

def start_sketch(model, plane_name="Front Plane"):
    """
    在指定基准面上开始草图

    参数:
        model: IModelDoc2
        plane_name: 基准面名称
            英文: "Front Plane", "Top Plane", "Right Plane"
            中文: "前视基准面", "上视基准面", "右视基准面"
    """
    model.Extension.SelectByID2(plane_name, "PLANE", 0, 0, 0, False, 0, None, 0)
    model.SketchManager.InsertSketch(True)


def end_sketch(model):
    """退出当前草图"""
    model.SketchManager.InsertSketch(True)


def sketch_line(model, x1, y1, x2, y2):
    """画直线（单位: 米）"""
    return model.SketchManager.CreateLine(x1, y1, 0, x2, y2, 0)


def sketch_rectangle(model, cx, cy, w, h):
    """以中心点画矩形（单位: 米）"""
    return model.SketchManager.CreateCenterRectangle(
        cx, cy, 0, cx + w / 2, cy + h / 2, 0
    )


def sketch_corner_rectangle(model, x1, y1, x2, y2):
    """以对角线画矩形（单位: 米）"""
    return model.SketchManager.CreateCornerRectangle(x1, y1, 0, x2, y2, 0)


def sketch_circle(model, cx, cy, radius):
    """画圆（单位: 米）"""
    return model.SketchManager.CreateCircleByRadius(cx, cy, 0, radius)


def sketch_arc(model, cx, cy, x1, y1, x2, y2, direction=1):
    """
    画圆弧

    参数:
        cx, cy: 圆心坐标（米）
        x1, y1: 起点坐标
        x2, y2: 终点坐标
        direction: 1=逆时针, -1=顺时针
    """
    return model.SketchManager.CreateArc(cx, cy, 0, x1, y1, 0, x2, y2, 0, direction)


def sketch_polygon(model, cx, cy, radius, sides=6):
    """画正多边形（内切圆方式）"""
    return model.SketchManager.CreatePolygon(cx, cy, 0, cx + radius, cy, 0, sides, True)


def sketch_slot(model, x1, y1, x2, y2, radius):
    """画槽口"""
    return model.SketchManager.CreateSketchSlot(
        0,  # swSketchSlotCreationType_e: 0=Straight
        radius, radius,  # 宽度
        x1, y1, 0,
        x2, y2, 0,
        0, 0, 0,
        1, False
    )


def sketch_spline(model, points):
    """
    画样条曲线

    参数:
        points: [(x1,y1), (x2,y2), ...] 控制点列表（单位: 米）
    """
    import array
    point_array = array.array('d')
    for x, y in points:
        point_array.extend([x, y, 0.0])
    return model.SketchManager.CreateSpline2(point_array, False)


def add_dimension(model, x, y):
    """在指定位置添加尺寸标注"""
    return model.AddDimension2(x, y, 0)


def add_sketch_relation(model, relation_type):
    """
    添加草图几何关系

    常用 relation_type:
        "sgFIXED", "sgHORIZONTAL", "sgVERTICAL", "sgCOLINEAR",
        "sgPARALLEL", "sgPERPENDICULAR", "sgTANGENT", "sgCONCENTRIC",
        "sgEQUAL", "sgSYMMETRIC", "sgMIDPOINT", "sgCOINCIDENT"
    """
    return model.SketchAddConstraints(relation_type)


# ============================================================
# 特征操作
# ============================================================

def extrude_boss(model, sketch_name, depth, direction=True, merge=True):
    """
    凸台拉伸

    参数:
        model: IModelDoc2
        sketch_name: 草图名称（如 "Sketch1"）
        depth: 拉伸深度（米）
        direction: True=正方向
        merge: True=合并结果
    """
    model.Extension.SelectByID2(sketch_name, "SKETCH", 0, 0, 0, False, 0, None, 0)
    return model.FeatureManager.FeatureExtrusion3(
        direction, False, False,
        0, 0,  # 终止条件: Blind
        depth, 0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False,
        merge, True, True, True, 0
    )


def extrude_cut(model, sketch_name, depth, direction=True, flip=False):
    """
    切除拉伸

    参数:
        model: IModelDoc2
        sketch_name: 草图名称
        depth: 切除深度（米），0 表示完全贯穿
        direction: True=正方向
        flip: True=翻转切除方向
    """
    model.Extension.SelectByID2(sketch_name, "SKETCH", 0, 0, 0, False, 0, None, 0)
    if depth == 0:
        # 完全贯穿
        end_condition = 1  # swEndCondThroughAll
        depth = 0.01  # 占位值
    else:
        end_condition = 0  # swEndCondBlind

    return model.FeatureManager.FeatureCut4(
        direction, flip, False,
        end_condition, 0,
        depth, 0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False, False,
        True, True, True, True,
        False, 0, 0, False, False
    )


def extrude_midplane(model, sketch_name, total_depth):
    """
    中面拉伸（两侧对称拉伸）

    参数:
        total_depth: 总深度（米），每侧为 total_depth/2
    """
    model.Extension.SelectByID2(sketch_name, "SKETCH", 0, 0, 0, False, 0, None, 0)
    return model.FeatureManager.FeatureExtrusion3(
        True, False, False,
        6, 0,  # 6 = swEndCondMidPlane
        total_depth, 0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False,
        True, True, True, True, 0
    )


def revolve_boss(model, sketch_name, angle_rad, axis_sketch_name=None):
    """
    旋转凸台

    参数:
        sketch_name: 轮廓草图名称
        angle_rad: 旋转角度（弧度），2*pi 表示 360 度
        axis_sketch_name: 旋转轴草图名称（None 则需预先选择轴线）
    """
    model.Extension.SelectByID2(sketch_name, "SKETCH", 0, 0, 0, False, 0, None, 0)
    return model.FeatureManager.FeatureRevolve2(
        True, True, False,
        False, False, False,
        0, 0,
        angle_rad, 0,
        False, False,
        0.0, 0.0,
        0, 0, 0, True, True, True
    )


def fillet(model, radius, edges=None):
    """
    倒圆角

    参数:
        model: IModelDoc2
        radius: 圆角半径（米）
        edges: 预先选择的边线列表，None 则使用当前选择
    """
    return model.FeatureManager.FeatureFillet(
        195, radius, 0, 0, None, None, None
    )


def chamfer(model, distance, angle_deg=45):
    """
    倒角

    参数:
        distance: 倒角距离（米）
        angle_deg: 倒角角度（度）
    """
    import math
    angle_rad = angle_deg * math.pi / 180.0
    return model.FeatureManager.InsertFeatureChamfer(
        4, 1, distance, angle_rad, 0, 0, 0, 0
    )


def linear_pattern(model, feature_name, d1_x, d1_y, d1_z, d1_spacing, d1_count,
                    d2_x=0, d2_y=0, d2_z=0, d2_spacing=0, d2_count=1):
    """
    线性阵列

    参数:
        feature_name: 要阵列的特征名称
        d1_*: 方向1 的方向向量、间距（米）和数量
        d2_*: 方向2（可选）
    """
    model.Extension.SelectByID2(feature_name, "BODYFEATURE", 0, 0, 0, False, 4, None, 0)
    return model.FeatureManager.FeatureLinearPattern3(
        d1_spacing, d2_spacing,
        d1_count, d2_count,
        False, False,
        str(d1_x), str(d1_y), str(d1_z),
        str(d2_x), str(d2_y), str(d2_z),
        False, False
    )


def circular_pattern(model, feature_name, axis_name, angle_rad, count, equal_spacing=True):
    """
    圆形阵列

    参数:
        feature_name: 要阵列的特征名称
        axis_name: 旋转轴名称
        angle_rad: 总角度（弧度）
        count: 实例数量
        equal_spacing: True=等间距
    """
    model.Extension.SelectByID2(feature_name, "BODYFEATURE", 0, 0, 0, False, 4, None, 0)
    model.Extension.SelectByID2(axis_name, "AXIS", 0, 0, 0, True, 1, None, 0)
    return model.FeatureManager.FeatureCircularPattern4(
        count, angle_rad, False, "None", False, equal_spacing, False
    )


def shell(model, thickness, faces_to_remove=None):
    """
    抽壳

    参数:
        thickness: 壁厚（米）
        faces_to_remove: 需预先选择要移除的面
    """
    return model.FeatureManager.InsertFeatureShell(thickness, False)


def mirror_feature(model, feature_name, mirror_plane_name):
    """
    镜像特征

    参数:
        feature_name: 要镜像的特征名称
        mirror_plane_name: 镜像基准面名称
    """
    model.Extension.SelectByID2(feature_name, "BODYFEATURE", 0, 0, 0, False, 4, None, 0)
    model.Extension.SelectByID2(mirror_plane_name, "PLANE", 0, 0, 0, True, 1, None, 0)
    return model.FeatureManager.InsertMirrorFeature2(False, False, False, False, 0)


def hole_wizard(model, hole_type, standard, fastener_type, size, depth, x, y, z):
    """
    异型孔向导（简化版）
    注意：完整的异型孔向导参数复杂，建议参考 API 文档调整
    """
    # 异型孔向导需要通过 FeatureManager.HoleWizard5 调用
    # 具体参数取决于孔类型，此处提供框架
    pass


def rib(model, sketch_name, thickness, direction=True):
    """
    筋特征

    参数:
        sketch_name: 筋轮廓草图名称
        thickness: 筋厚度（米）
        direction: 拉伸方向
    """
    model.Extension.SelectByID2(sketch_name, "SKETCH", 0, 0, 0, False, 0, None, 0)
    return model.FeatureManager.InsertRib(
        direction, False, thickness, 0, False, False, False, 0, False
    )
