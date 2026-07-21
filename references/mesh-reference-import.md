# 高还原网格参考模型导入

当用户要求汽车、消费电子、人物雕塑等“原版外观”“1:1 复刻”“不像概念版”的模型时，先判断目标到底是工程可编辑实体，还是外观高还原参考。外观高还原通常应优先使用公开三维模型或多视图蓝图作为基准，不要从零手搓一堆低保真棱柱后再反复精修。

## 适用场景

- 用户明确要求外观像真实产品，例如“小米 SU7 原版”“按公开图 1:1 复刻”。
- 目标是展示、比例核对、外观参考、后续逆向重建底稿。
- 输入是 `.glb`、`.gltf`、`.obj`、`.stl`、`.fbx`、`.blend` 等网格或 DCC 模型。

不适合的场景：

- 用户需要可参数编辑的机械特征、可出工程图制造的 Class-A 曲面或钣金结构。
- 用户要求内部结构、装配约束、尺寸公差、工艺特征，这时应重新建模或分件逆向，不要把三角网格说成工程实体。

## 路线选择

1. 先找可靠输入：用户提供的模型文件优先；其次使用公开可下载模型；最后才用正侧俯后蓝图重建轮廓。
2. 记录来源和许可：公开模型也要记录 URL、作者、许可证、下载日期；非商用声明不等于可以忽略署名或相同许可条款。
3. 保留原始文件：把原始 GLB/FBX/OBJ 和转换后的 OBJ/STL 放在同一工作目录，写 `manifest.json`。
4. 统一尺度和坐标：先用工具检查包围盒，再按真实公称尺寸缩放；汽车常用 `X=宽`、`Y=高`、`Z=长`。
5. 优先导入 OBJ：OBJ 更可能保留材质、透明玻璃、灯组和内饰；STL 稳定但通常丢材质。
6. 导入 SolidWorks 后必须目视审查四视图。规则评分 pass 只能说明“不是空白/文件存在”，不能说明“像用户要的对象”。

## GLB/FBX/BLEND 转换建议

SolidWorks 对 GLB/FBX/BLEND 支持不稳定，建议先转换：

- Blender 可用时：用 Blender 导入后导出 OBJ/STL，保留纹理目录。
- Python 可用时：用 `trimesh` 读取 GLB，导出 OBJ/STL；若要保留材质，优先导出 OBJ。
- 高面数模型不要直接转 STEP。网格转 STEP 会生成大量三角面 BREP，SolidWorks `LoadFile4` 容易卡死或 RPC 断开。

### Python 可选依赖

网格转换不是普通 SolidWorks 建模的核心依赖，但遇到 GLB/GLTF/OBJ/STL 检查、缩放、纹理导出时应提前检查：

| 库 | 用途 |
|---|---|
| `trimesh` | 读取 GLB/GLTF/OBJ/STL、计算包围盒、导出 OBJ/STL/PLY |
| `pygltflib` | 更细粒度解析 GLTF/GLB 元数据和资源 |
| `numpy` | 尺度变换、坐标轴处理 |
| `Pillow` | 纹理图片读写和预览辅助 |

检查命令：

```powershell
python - <<'PY'
import importlib.util
for name in ["trimesh", "pygltflib", "numpy", "PIL"]:
    print(name, "OK" if importlib.util.find_spec(name) else "MISSING")
PY
```

缺失时提示用户安装：

```powershell
python -m pip install -r SKILL_DIR\requirements-mesh.txt
```

如果只是打开已有 OBJ/STL 并导入 SolidWorks，不一定需要这些库；如果要从 GLB/FBX/BLEND 转换或按真实尺寸重缩放，通常需要。

示例尺度处理：

```python
import numpy as np
import trimesh

scene = trimesh.load(r"E:\source\SU7.glb", force="scene")
mesh = scene.dump(concatenate=True)

# 源模型轴向：X=宽，Y=高，Z=长；目标尺寸单位 m。
target_extents = np.array([1.963, 1.455, 4.997])
scale = target_extents / scene.extents
center_xz = np.array([
    (scene.bounds[0][0] + scene.bounds[1][0]) / 2,
    0,
    (scene.bounds[0][2] + scene.bounds[1][2]) / 2,
])

vertices = mesh.vertices.copy()
vertices[:, 0] = (vertices[:, 0] - center_xz[0]) * scale[0]
vertices[:, 1] = (vertices[:, 1] - scene.bounds[0][1]) * scale[1]
vertices[:, 2] = (vertices[:, 2] - center_xz[2]) * scale[2]
mesh.vertices = vertices

mesh.export(r"E:\work\reference_scaled_m.obj")
mesh.export(r"E:\work\reference_scaled_m.stl")
```

## SolidWorks 稳定导入写法

优先使用：

```powershell
python scripts\sw_import_mesh_reference.py `
  E:\work\reference_scaled_m.obj `
  E:\work\reference_obj.SLDPRT `
  --units m `
  --model-type graphics `
  --review-dir E:\work\review_obj
```

关键细节：

- OBJ/STL 不要用 `OpenDoc6()` 当普通零件打开；部分 SW2024 环境会返回 `errors=2097152`。
- OBJ/STL 走 `LoadFile4()` 时第三个参数不要传 `None`，否则会触发 `类型不匹配`。
- 稳定写法是 `LoadFile4(path, "r", create_empty_dispatch_variant(), errors)`。
- STEP/STP/IGES/IGS 仍按 `sw_connect.open_document()` 的外来 CAD 路线：`GetImportFileData()` + `LoadFile4(..., "r", import_data, errors)`。
- 高面数外观模型默认导入为 `graphics`；只有明确需要尝试实体修补时才用 `surface` 或 `solid`。

## 审查标准

导入后至少检查：

1. 输出 `.SLDPRT` 存在且大小合理。
2. `run_review()` 导出 `isometric/front/top/right` 四视图。
3. 等轴测能看到主体外观，正/侧/俯视比例符合目标对象。
4. 关键识别特征存在：例如汽车的车顶线、灯组、轮毂、侧窗、前后包围。
5. 颜色和材质不是被选择高亮污染；截图前调用 `ClearSelection2(True)`。
6. 给用户说明模型类型：网格参考模型不是官方参数曲面，后续若要制造级模型，需要基于它分件逆向重建。

## 本次 SU7 经验摘要

- 错误路线：用脚本手搓分层棱柱/胶囊车壳，然后不断补灯、轮毂、玻璃。用户要“原版 SU7”时，这种底稿再精修也会偏离目标。
- 正确路线：找到公开 SU7 网格模型，保留来源和许可，转 OBJ/STL，按 `4997 × 1963 × 1455 mm` 缩放，再导入 SolidWorks。
- 关键 API 坑：`OpenDoc6()` 打 OBJ/STL 失败并不代表文件坏；`LoadFile4()` 传 `None` 也会失败。必须传空 Dispatch 变体。
- 材质经验：OBJ 比 STL 更可能保留玻璃、尾灯、内饰、轮毂材质；STL 适合作为无材质兜底。
- 审查经验：自动评分 pass 不等于像 SU7。必须打开预览图肉眼看品牌特征、比例和是否有零件飞出。
