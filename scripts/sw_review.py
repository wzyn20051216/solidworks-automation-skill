"""
SolidWorks 结果自审查工具。

用途:
    生成或修改 CAD 后，导出多视角预览图并收集基础模型摘要，帮助代理通过截图
    或导出的 BMP 判断几何是否符合用户意图。
"""
import os
from pathlib import Path

from sw_connect import get_com_member


STANDARD_VIEWS = {
    "front": 1,
    "back": 2,
    "left": 3,
    "right": 4,
    "top": 5,
    "bottom": 6,
    "isometric": 7,
    "trimetric": 8,
    "dimetric": 9,
}


def _expand_path(path):
    """展开输出路径。"""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def zoom_to_fit(model):
    """缩放到适合窗口并刷新图形。"""
    get_com_member(model, "ViewZoomtofit2")
    get_com_member(model, "GraphicsRedraw2")


def set_standard_view(model, view_name="isometric"):
    """
    设置标准视图方向。

    参数:
        view_name: "isometric"、"front"、"top"、"right"，也可传 SolidWorks 视图名。
    """
    view_id = STANDARD_VIEWS.get(str(view_name).lower())
    if view_id is None:
        model.ShowNamedView2(str(view_name), -1)
    else:
        model.ShowNamedView2("", view_id)
    zoom_to_fit(model)


def save_preview(model, output_path, view_name="isometric", width=1600, height=1000):
    """
    导出当前模型预览图。

    参数:
        model: IModelDoc2 对象
        output_path: BMP 输出路径
        view_name: 标准视图方向
        width: 导出图片宽度
        height: 导出图片高度

    返回:
        输出路径字符串
    """
    output_path = _expand_path(output_path)
    if output_path.suffix.lower() != ".bmp":
        output_path = output_path.with_suffix(".bmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    set_standard_view(model, view_name)
    ok = model.SaveBMP(str(output_path), int(width), int(height))
    if not ok or not output_path.exists():
        raise RuntimeError(f"预览图导出失败: {output_path}")
    return str(output_path)


def save_review_previews(model, output_dir, basename="review", views=None):
    """
    导出多视角预览图。

    参数:
        model: IModelDoc2 对象
        output_dir: 输出目录
        basename: 文件名前缀
        views: 视图列表，默认导出等轴测、前视、俯视、右视

    返回:
        预览图路径列表
    """
    views = views or ("isometric", "front", "top", "right")
    output_dir = _expand_path(output_dir)
    return [
        save_preview(model, output_dir / f"{basename}_{view}.bmp", view)
        for view in views
    ]


def collect_model_summary(model):
    """
    收集基础模型摘要。

    返回:
        dict，包含标题、类型、特征数量、保存路径等信息。
    """
    features = []
    feature_error = None
    try:
        feature = get_com_member(model, "FirstFeature")
        while feature:
            features.append({
                "name": get_com_member(feature, "Name"),
                "type": get_com_member(feature, "GetTypeName2"),
            })
            feature = get_com_member(feature, "GetNextFeature")
    except Exception as exc:
        feature_error = str(exc)

    summary = {
        "title": get_com_member(model, "GetTitle"),
        "path": get_com_member(model, "GetPathName"),
        "type": get_com_member(model, "GetType"),
        "feature_count": len(features),
        "features": features,
    }
    if feature_error:
        summary["feature_error"] = feature_error
    return summary
