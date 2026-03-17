"""
SolidWorks 装配体操作工具
"""
import win32com.client
import pythoncom
from win32com.client import VARIANT


def add_component(asm_model, part_path, x=0, y=0, z=0, config_name=""):
    """
    向装配体添加零部件

    参数:
        asm_model: IAssemblyDoc (装配体文档)
        part_path: 零件/子装配体文件路径
        x, y, z: 放置位置（米）
        config_name: 配置名称，空字符串使用默认配置

    返回:
        IComponent2 对象
    """
    component = asm_model.AddComponent4(part_path, config_name, x, y, z)
    if component:
        print(f"已添加组件: {part_path}")
    else:
        print(f"添加组件失败: {part_path}")
    return component


def add_mate_coincident(asm_model, entity1_name, entity1_type, entity2_name, entity2_type):
    """
    添加重合配合

    参数:
        entity1_name/entity2_name: 实体名称（面、边、点等）
        entity1_type/entity2_type: 实体类型字符串（"FACE", "PLANE", "EDGE", "VERTEX" 等）
    """
    asm_model.ClearSelection2(True)
    asm_model.Extension.SelectByID2(entity1_name, entity1_type, 0, 0, 0, False, 1, None, 0)
    asm_model.Extension.SelectByID2(entity2_name, entity2_type, 0, 0, 0, True, 1, None, 0)
    return asm_model.AddMate5(
        0,    # swMateCoincident
        0,    # swMateAlignALIGNED
        False, 0, 0, 0, 0, 0, 0, 0, 0, False
    )


def add_mate_concentric(asm_model, face1_name, face2_name):
    """添加同心配合"""
    asm_model.ClearSelection2(True)
    asm_model.Extension.SelectByID2(face1_name, "FACE", 0, 0, 0, False, 1, None, 0)
    asm_model.Extension.SelectByID2(face2_name, "FACE", 0, 0, 0, True, 1, None, 0)
    return asm_model.AddMate5(
        1,    # swMateConcentric
        0, False, 0, 0, 0, 0, 0, 0, 0, 0, False
    )


def add_mate_distance(asm_model, entity1_name, entity1_type, entity2_name, entity2_type, distance):
    """
    添加距离配合

    参数:
        distance: 配合距离（米）
    """
    asm_model.ClearSelection2(True)
    asm_model.Extension.SelectByID2(entity1_name, entity1_type, 0, 0, 0, False, 1, None, 0)
    asm_model.Extension.SelectByID2(entity2_name, entity2_type, 0, 0, 0, True, 1, None, 0)
    return asm_model.AddMate5(
        5,    # swMateDistance
        0, False, distance, distance, distance, 0, 0, 0, 0, 0, False
    )


def add_mate_parallel(asm_model, face1_name, face2_name):
    """添加平行配合"""
    asm_model.ClearSelection2(True)
    asm_model.Extension.SelectByID2(face1_name, "FACE", 0, 0, 0, False, 1, None, 0)
    asm_model.Extension.SelectByID2(face2_name, "FACE", 0, 0, 0, True, 1, None, 0)
    return asm_model.AddMate5(
        3,    # swMateParallel
        0, False, 0, 0, 0, 0, 0, 0, 0, 0, False
    )


def get_components(asm_model, top_level_only=True):
    """
    获取装配体中的所有组件

    参数:
        top_level_only: True=仅顶层组件, False=包含子装配体中的组件

    返回:
        组件信息列表
    """
    components = asm_model.GetComponents(top_level_only)
    result = []
    if components:
        for comp in components:
            result.append({
                "name": comp.Name2,
                "path": comp.GetPathName(),
                "suppressed": comp.IsSuppressed(),
                "visible": comp.Visible,
            })
    return result


def suppress_component(asm_model, component_name):
    """压缩（隐藏）组件"""
    asm_model.Extension.SelectByID2(component_name, "COMPONENT", 0, 0, 0, False, 0, None, 0)
    asm_model.EditSuppress()


def unsuppress_component(asm_model, component_name):
    """解压缩（显示）组件"""
    asm_model.Extension.SelectByID2(component_name, "COMPONENT", 0, 0, 0, False, 0, None, 0)
    asm_model.EditUnsuppress()


def replace_component(asm_model, old_component_name, new_part_path):
    """
    替换装配体中的组件

    参数:
        old_component_name: 旧组件名称
        new_part_path: 新零件文件路径
    """
    asm_model.Extension.SelectByID2(old_component_name, "COMPONENT", 0, 0, 0, False, 0, None, 0)
    return asm_model.ReplaceComponents2(new_part_path, "", False, 0, True)


def get_interference_detection(asm_model):
    """运行干涉检查"""
    interference = asm_model.InterferenceDetection
    interference.TreatSubAssembliesAsComponents = False
    interference.TreatCoincidenceAsInterference = False
    interference.Done()

    count = interference.GetInterferenceCount()
    print(f"检测到 {count} 处干涉")
    return count
