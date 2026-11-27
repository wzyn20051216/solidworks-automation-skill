# 零件规格外形验收的 SW2024 回归

规格中的 `verify.envelope_mm` 会按公差比较零件在模型 XYZ 方向的外形尺寸。此前该比较直接使用 `IPartDoc.GetPartBox(True)` 的近似结果。修正后使用当前配置中各实体沿六个轴向的 `IBody2.GetExtremePoint`，合成整个零件的范围。任一方向无法测量时，该外形项报告无法验证。

## 真机结果

SolidWorks 2024 SP0.1（Revision 32.0.1）、Windows 11、Python 3.14.7，Python COM 后端 `SldWorks.Application.32`。在可见桌面会话内运行，测量脚本附着既有实例。

| 对照 | 独立预期外形 XYZ（mm） | 近似包围盒（mm） | 实体极值（mm） | 规格验收 |
| --- | --- | --- | --- | --- |
| 箱盖同一保存版本的只读副本 | 104 × 116 × 10 | 104 × 116 × 10.428963 | 104 × 116 × 10 | 公差 0.05 mm，旧源码 `warn`，修正源码 `pass` |
| 倾斜 30° 的椭圆柱，半轴 40 / 10 mm，拉伸 6 mm | 70 × 43.588989435… × 6 | 70 × 43.588989 × 6 | 70 × 43.588989 × 6 | 公差 0.001 mm，保存前和关闭重开后均 `pass` |

箱盖的两轮读数来自同一个副本文件。使用 `base.type="none"`，通过实际 `build_from_spec` 执行外形验收。只读副本重建及特征健康检查通过，回读为一个实体。原件与副本的 SHA-256 在测量前后均一致。椭圆柱用解析投影得到轴向预期尺寸，另核对原生实体体积与特征健康。等轴测预览已目视复核，关闭重开后读数一致。测试文档均已关闭，结束时打开文档数为 0，保留可见 SolidWorks 实例。箱盖模型和原始报告保留在本机。

受测生产源码 SHA-256：

- `scripts/sw_measure.py`: `9f69438ff63256c7392d405751e827d78ddb3a064fe69c90a082be87b1d48c51`
- `scripts/build_from_spec.py`: `910e8e326d53552d372fbda39bfb1742fd1ece8d4d0dcaabd2414c48597cc59c`

## 复跑

使用唯一、可见且没有打开文档的 SolidWorks 实例。PID 用当前实例的值，输出目录须不存在。

```powershell
python tests/manual_spec_envelope_regression.py --version <SolidWorks年份> --process-id <PID> --output output/spec-envelope-new-run
```

脚本创建椭圆柱，回读近似包围盒和实体极值并运行真实规格验收，保存关闭后只读重开复测。输出 `native-report.json` 和等轴测预览。该自制件用于验证真实 COM 极值读取及保存重开，两个测量方法在此件上读数相同。离线回归 `tests/test_build_from_spec.py` 提供近似值偏大、极值失败两组可重复的差异对照。聚合多实体极值、空实体和无效坐标由 `tests/test_sw_measure.py` 覆盖。

本次范围为零件在当前配置下相对模型坐标轴的实体外形。SW2026 尚未实测。装配体精确测量、运动、干涉、载荷及制造验收不在本次范围。
