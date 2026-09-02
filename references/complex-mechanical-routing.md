# 复杂机械模型能力路由

## 先探测，再执行

复杂机械任务开始前运行：

```powershell
python scripts\sw_capability_probe.py --output capability_report.json
```

报告同时区分：

- `type_library_present`：本机安装包含接口定义。
- `implementation_status`：本技能是否已有经过真实回归的封装。
- `ready_for_unattended_use`：是否允许无人值守执行。

类型库存在不等于许可证可用，也不等于自动化已验证。`reference_only`、`not_implemented` 和缺少证据的 `pilot` 禁止向用户宣称已完成。

## 当前能力等级

| 领域 | 当前等级 | 执行规则 |
|---|---|---|
| 参数化零件、孔槽、圆角倒角 | Verified | 可走真实 COM，必须输出参数 JSON 和审查报告 |
| 装配、同心/距离/齿轮 Mate | Verified | 必须检查自由度和 Mate 特征树 |
| Motion Study 旋转马达 | Verified | 计算后调用 `collect_motion_study_summary()` 检查结果是否过期 |
| 工程图 | Pilot | 必须人工复核图框、视图、尺寸链和 GB/T 格式 |
| 配置、设计表 | Reference only | 先做最小样件回归，再用于客户模型 |
| 钣金 | Pilot（SW2026 开放轮廓基体法兰） | 必须回读原生 SheetMetal/BaseFlange/FlatPattern、制造参数，并验证重开与 DXF |
| 焊件 | Pilot（SW2026 HSS 平面框架） | 必须回读 WeldmentFeature/WeldMemberFeat、每项实体数、长度、数量、角度、来源属性及重开证据 |
| 复杂曲面、模具 | Pilot | `create-ocp-loft/create-ocp-surface` 可生成并重开受限直纹/平滑 Loft、Sweep/Knit/Thicken；G1/G2 和曲率半径只使用离散采样证据，复杂路径和模具仍门禁 |
| Routing | Pilot | 只能运行 `routing-preflight` 或 `check-routing`；无加载项/许可证证据时原生写入必须 blocked |
| Simulation/FEA | Pilot | `run-fea` 可运行受限线性/非线性静力并解析最终步接触穿透/压力/滑移，`run-fea-convergence` 执行 3-8 档线性或非线性网格序列；塑性、接触和收敛均必须保留工程复核 |

## 复杂零件

1. 将模型拆成基础体、主功能特征、接口特征、制造特征和外观特征。
2. 优先稳定基准、全约束草图和命名特征；禁止依赖 `Edge1`、屏幕坐标或偶然选择顺序。
3. 复杂曲面必须明确连续性目标（G0/G1/G2）、分型/拔模、厚度和可制造方式。
4. 钣金必须记录板厚、材料、内折弯半径、K 因子/折弯表、折弯方向和展开 DXF。
5. 焊件必须记录型材标准、切割长度、斜接、焊缝、切割清单和加工余量。
6. 配置/设计表必须验证每个配置可重建、质量属性合理、输出文件命名无碰撞。

## 复杂装配与运动

1. 建立自由度预算：每个移动件先列出预期 6 自由度，再逐个 Mate 消除。
2. 旋转件使用同心 Mate + 轴向定位，不锁旋转；直线件使用槽/距离/限位配合。
3. 接触、摩擦、弹簧、阻尼、重力和碰撞不属于当前“旋转马达已验证”范围。
4. 运动交付必须包含：算例类型、时长、马达数量、外力数量、特征数量、结果存在性和 `results_out_of_date`。
5. 可播放动画不能证明机构正确；还要检查干涉、行程极限、速度/加速度、驱动力/扭矩和 Mate 反力。
6. Motion Analysis 结果依赖加载项和许可证，缺失时明确降级为 Animation/Basic Motion，不能伪造分析结果。

## 新能力开发门禁

1. 从本机 `.tlb` 或 SolidWorks 官方 API 文档确认接口、签名、枚举和版本。
2. 创建最小回归样件，不直接在用户复杂装配上试错。
3. 封装成 `scripts/sw_*.py` 的窄接口，所有 COM 返回值显式检查。
4. 添加静态测试和真实 SolidWorks 回归脚本。
5. 生成机器可读验收证据和多视图预览。
6. 把失败模式写入 `references/troubleshooting.md` 后才能把能力标为 Pilot；连续真实回归通过后才能标为 Verified。
