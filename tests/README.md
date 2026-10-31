# tests/ 目录说明

本目录混放两类测试，**运行方式与证据效力完全不同**，不要混为一谈。

| 类别 | 命名 | 是否被 pytest 收集 | 是否需要真机 CAD | 证据效力 |
| --- | --- | --- | --- | --- |
| 单元/契约测试 | `test_*.py` | ✅ 是（`pyproject.toml` 的 `testpaths = ["tests"]`） | ❌ 否 | 离线回归，可进 CI |
| 真机回归脚本 | 其余 `.py`（含 `__main__`） | ❌ 否 | ✅ 是 | 只能在装有 CAD 的 Windows 机器上执行 |

```bash
# 离线回归（CI 执行的就是这一条）
python -m pytest -q

# 真机脚本（不会被 pytest 收集，必须手动执行）
python tests/solidworks_golden_workflow.py --case mounting_bracket --output output/run --runs 1
```

---

## 真机回归脚本清单

前置条件（除表内特别说明外，均需）：

- Windows 10/11 x64 + 合法许可的 SolidWorks（基线 2026 SP01.1 / 2024）
- `python -m pip install -r requirements.txt`
- 已运行 `python scripts/cad_doctor.py` 且 `installations.solidworks.registered = true`
- **脚本自己管理 SolidWorks 会话**，执行前请关闭其他占用 COM 的进程

耗时列为**粗估**（单次、SolidWorks 已安装且磁盘不冷启动）。标 ✅ 的是有实测记录的值。

### Golden 用例（正式验收）

| 脚本 | 用途 | 额外前置 | 预估耗时 |
| --- | --- | --- | --- |
| `solidworks_golden_workflow.py` | Golden 统一入口。`--case` 选择用例，`--runs 1..5`，`--expected-terminal completed\|blocked` | `--expected-terminal blocked` 必须配 `--runs 5` | 单轮 6–50 min ✅ |
| `solidworks_golden_mounting_bracket_2026.py` | 安装板 + 4×Ø7 贯穿孔，尺寸/体积容差核验 | — | 单轮 6–15 min ✅ |
| `solidworks_golden_parallel_gripper_2026.py` | 双指平行夹爪装配，Mate 与自由度核验 | — | 单轮 10–30 min ✅ |
| `solidworks_golden_gripper_travel_2026.py` | 夹爪机械保持 + 3×3 静态全行程 + 越限穿透注入 | — | 单轮 6–40 min ✅ |

> 五轮正式验收的最佳记录为 2 小时左右；单轮耗时会随 SolidWorks 冷启动与内存状态波动。
> `run-05` 曾因窗口被人工关闭而 COM 断开，故**不要在运行期间操作那台机器**。

### 建模与交付

| 脚本 | 用途 | 额外前置 | 预估耗时 |
| --- | --- | --- | --- |
| `solidworks_add_component_regression.py` | 装配体插入组件与定位 | — | 1–3 min |
| `solidworks_appearance_regression.py` | 外观/材质应用与回读 | — | 1–3 min |
| `solidworks_configuration_family_regression.py` | 配置族与设计表驱动 | — | 2–5 min |
| `solidworks_model_health_regression.py` | 模型健康检查（重建、错误特征） | — | 1–2 min |
| `solidworks_sheet_metal_regression.py` | 钣金与展开 | — | 2–5 min |
| `solidworks_sketch_selection_regression.py` | 草图语义选边/选面 | — | 1–3 min |
| `solidworks_spur_gear_regression.py` | 渐开线直齿轮实体 | — | 1–3 min |
| `solidworks_sprocket_live.py` | 近似链轮实体、轴孔与重开；草图约束需复核 | `python tests/solidworks_sprocket_live.py` | 1–3 min |
| `solidworks_rename_copy_live.py` | 属性预览、两个独立零件副本和打开文档保护 | `python tests/solidworks_rename_copy_live.py` | 1–3 min |
| `solidworks_spring_live.py` | 开放端弹簧实体、旋向回读、极值尺寸与重开 | `python tests/solidworks_spring_live.py` | 1–3 min |
| `solidworks_weldment_regression.py` | 焊件与切割清单 | — | 2–5 min |
| `solidworks_week3_delivery_regression.py` | 第 3 周交付链路（多能力串联） | — | 5–15 min |
| `solidworks_week4_drawing_regression.py` | 第 4 周工程图 + BOM | 需要 A3 图框（`*.slddrt`），见下 | 5–15 min |
| `solidworks_drawing_version_matrix.py` | 工程图跨版本矩阵 | 多版本 SolidWorks | 10–30 min |
| `solidworks_loadfile4_import_regression.py` | 外部文件导入（LoadFile4） | 自备 STEP/IGES 输入 | 2–5 min |
| `solidworks_pack_worker_regression.py` | Pack and Go 打包 | — | 2–5 min |
| `solidworks_reliability_b_regression.py` | 方案 B 可靠性回归（状态/恢复） | — | 5–15 min |
| `solidworks_addin_host_regression.py` | C# 加载项宿主与 37 个 COM 回调 | 需先构建 `dotnet/` 下的加载项 DLL | 3–8 min |
| `cad_studio_weekly_regression.py` | CAD Studio CLI 周回归编排 | — | 5–15 min |
| `live_smoke_new_tools.py` | 新工具真机冒烟（逐工具） | — | 3–10 min |

> **A3 图框**：`solidworks_week4_drawing_regression.py` 的图框候选来自
> `discover_installations("solidworks")` 的安装目录、`SOLIDWORKS_TYPELIB_DIRS` 与 `%ProgramData%\SOLIDWORKS`。
> 若三者都没有 `*a3*.slddrt`，该脚本会因缺少图框而失败——这是环境缺失，不是代码缺陷。

### AutoCAD

| 脚本 | 用途 | 额外前置 | 预估耗时 |
| --- | --- | --- | --- |
| `autocad_week4_drawing_regression.py` | DWG 绘图、图层、标注、预览 | **AutoCAD 2024** + .NET 加载项 | 5–15 min |

### CalculiX（FEA）

| 脚本 | 用途 | 额外前置 | 预估耗时 |
| --- | --- | --- | --- |
| `calculix_nonlinear_regression.py` | 非线性静力求解与结果审计 | `ccx.exe`（见 `CADSTUDIO_SOLVER_DIRS`） | 2–10 min |
| `calculix_nonlinear_convergence_regression.py` | 网格收敛性检查 | 同上 | 5–20 min |

`ccx.exe` 的查找顺序：`CADSTUDIO_SOLVER_DIRS` → `D:\`、`E:\` 优先 → 本机全部盘符下的
`CADStudio\CalculiX-2.23\calculix_2.23_4win\ccx.exe`。

### MCP 原生线束（一次性人工验收）

| 脚本 | 用途 | 额外前置 | 预估耗时 |
| --- | --- | --- | --- |
| `manual_native_wire_2026.py` | 通过真实 MCP 注册工具验收 SW2026 原生线束读写，只操作本轮自建实例与文件 | 运行前**不得存在任何 SolidWorks 进程**（否则直接退出）；需要 `pywin32`、可导入 `mcp-server/server.py`；两个位置参数 `<repo-root> <不存在的输出目录>`（脚本用 `mkdir(exist_ok=False)` 建目录） | 5–15 min ✅ |

用法：

```powershell
python tests\manual_native_wire_2026.py "$PWD" "$PWD\output\native-wire-$(Get-Date -Format yyyyMMddHHmm)"
```

---

## 与 CI 的关系

本仓库的 CI 采用**混合方案**（2026-10-27 决策）：

| 作业 | 运行位置 | 是否必需合并检查 | 内容 |
| --- | --- | --- | --- |
| `test-and-build`（`windows-release.yml`） | GitHub 托管 `windows-2022` | **是**（`main` 的唯一必需检查） | 治理单测 + `pytest` + 离线 eval + 前端/Rust 构建 + 发布契约 |
| `authorize` / `cad-regression`（`windows-cad-regression.yml`） | `ubuntu-24.04` + `[self-hosted, Windows, CAD]` | **否**（手动 `workflow_dispatch`） | 治理准入 + 真实 CAD Golden |

由此产生三条必须遵守的口径：

1. **远程 CAD 真机测试不是合并前置条件。** 当前仓库自托管 Runner 数为 0，该工作流无法被调度，
   因此它既不能作为门禁，也不能作为证据来源。
2. **真实 CAD 验收只在维护者本机进行**，结果写入本地证据包，不进入 CI。
   `capabilities.yaml` 中标注 `verified` 的真机能力，其证据来自本机五轮执行，不是远端 CI。
3. **不得声称"远程 CAD CI 已通过"。** 离线 `pytest` 由托管 `test-and-build` 执行，这一层是真跑过的；
   真机层没有远端运行记录。

其它说明：

- 真机脚本**不会**被 CI 的 pytest 收集，也不应该被收集——它们需要 GUI 与授权。
- 若将来登记了自托管 Runner，需要**同时**补齐 `cad-validation` Environment 与只读审计令牌，
  该工作流才会真正可执行；届时是否把它升级为必需检查需要单独评估（自托管 Runner 会执行工作流中的任意代码）。

## 结论口径

- `pytest` 全绿只证明离线逻辑正确，**不证明** SolidWorks 真的能跑通。
- 真机脚本通过只证明**本机**这台 CAD 环境通过，**不证明**其他机器可部署。
- 两者都不等于远程 CI 通过。三者必须分别报告。
