# Issue #82：重开零件通孔诊断与回归

## 当前结论

[原报告](https://github.com/wzyn20051216/solidworks-automation-skill/issues/82)指向 SolidWorks 2024 build `32.5.0`，项目 `v2.1.1` / `36bc337`。报告称同一孔封装在新建零件成功，在重开零件上 `FeatureCut4` 返回空；同坐标裸草图切除成功。

Issue 列出了脚本、输出和零件文件名，但目前没有可下载的附件链接；本机只有 SolidWorks 2026。**SW2024 根因尚未确认，不能把 2026 回归通过描述为 #82 已解决。** 本批不修改切除方向、终止条件、草图选择策略或自动重试行为，不关闭原 Issue。

## 交付内容

- 圆孔切除返回空时抛出兼容 RuntimeError 的 `HoleFeatureCreationError`，保留原错误前缀，并带 `SW_HOLE_NOT_CREATED`。
- 失败后只读回读选择数量、是否仍在编辑草图、实体数量、草图实体及轮廓数量，以及请求的平面、草图、深度和固定方向语义。
- MCP 保留结构化 `diagnostics`，明确 `retryable=false`。某个 COM 诊断成员读取失败时记录 null，不覆盖原失败。
- 诊断状态明确为 `after_failed_cut`，不是调用前的选择快照。不将读取失败推断为“没有实体”或“没有草图”。
- 不保存、删除失败草图或重复执行切除；诊断不包含文档路径、PID 或模型几何。

## 可重复的原生验收

在唯一、版本明确的空白 SolidWorks 会话中运行，或让脚本启动本轮实例。输出目录必须不存在：

```powershell
python tests/manual_hole_reopen.py --version 2026 --output output/hole-reopen-new-run
# 在 SW2024 原环境采集相同矩阵，不代表本轮已执行：
python tests/manual_hole_reopen.py --version 2024 --output output/hole-reopen-2024-new-run
```

脚本新建 80×60×20 mm 板，分别使用空板、已有一个 6 mm 通孔的板作基线。对照新建封装、保存重开封装、重开后清空草图缓存、裸草图切除，以及独立 MCP stdio 重开并调用孔工具。所有成功调用均校验实际实体体积变化约 `565.486678 mm³`，并检查重建健康、再次保存重开及原生预览。

另用不与实体相交的孔验证失败诊断和体积保持不变。脚本只清理本轮登记的测试件；退出用户已启动的实例不在脚本所有权内。

## 本轮 SW2026 结果

SolidWorks 2026 SP1.1（`34.1.1`）中上述 10 个成功对照均通过，新增孔的实际体积变化为 `565.486677646157` 至 `565.486677646171 mm³`，符合 6 mm 孔贯穿 20 mm 板的计算值。已有孔保留；独立 MCP 创建的结果保存重开后体积保持正确，重建无错误、警告或未知状态。单孔、双孔原生预览已目视检查。

直接 API 和独立 MCP 对不相交孔均返回新诊断：选择数 1、非编辑草图状态、1 个实体、草图 1 个实体及 1 个轮廓；MCP 回读 `SW_HOLE_NOT_CREATED` 和 `retryable=false`。失败后实体体积不变，无自动重试。结束时本轮文档关闭、自启进程退出，进程清单恢复。

被测生产文件 SHA-256：

- `scripts/sw_part.py`：`5661ebb75bee0a8c11a2e31acee078111c3dc7d3ae90e0782a56e5d5034ea066`
- `scripts/sw_hole_features.py`：`248ed52385728e57806f35d21c255d39243e7182cc9e000493c8f1701dbf1eca`

原始模型、BMP 和报告保留本机；此记录不包含机器路径或 PID。这里验证的是 2026 回归及诊断功能，不是原 SW2024 故障修复证据。

## 后续根因门禁

需要原报告的 `repro_hole_bug.py`、输出及 `repro_plate.SLDPRT`，并在 SW2024 `32.5.0` 重现。重点比较：创建前后的实际草图引用、选择集、草图平面与实体相交方向，以及封装与裸调用的真实参数和文档身份。

官方 [FeatureCut4 文档](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featurecut4.html)区分 `Sd`、`Dir`、两端终止条件及实体作用域。返回空本身不足以确定根因，不根据版本年份直接反向切除，也不靠增加无界重试掩盖失败。

## 离线回归记录

基于 `524a4a3` 的独立诊断分支运行 `python -m pytest -q`：1766 项通过、17 项跳过，另有两条既有依赖警告。整合 ROT 修复后的 `ad4b457` 主线，再验证连接归属、文档身份、孔诊断、草图选择及发布合同：71 项通过。

```powershell
python -m pytest -q tests/test_sw_session_ownership.py tests/test_mcp_hole_diagnostics.py tests/test_sw_hole_features.py tests/test_sw_connect_open_document.py tests/test_mcp_document_identity.py tests/test_mcp_document_binding_integration.py tests/test_sw_part_sketch_selection.py tests/test_release_check.py tests/test_sync_bundled_skill.py
python scripts/validate_skill.py
python scripts/release_check.py
```

内嵌 Skill 同步、完整性和发布合同检查通过；这些离线结果不替代 SW2024 原故障的真机验收。
