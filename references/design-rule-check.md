# 中性文档设计规则审计（pilot）

DRC 检查提供的 `NeutralCadDocument` 证据，覆盖孔位、壁厚、标准件、装配、图纸关系和可选电机选型；它与关注制造工艺的 `check-dfm` 互补。检查结果仅用于工程复核，**不能替代真实模型测量、标准符合性验证或工程师签署**。

```powershell
python scripts/cad_studio.py list-drc-rules
python scripts/cad_studio.py check-drc --input examples/drc_sample_part.cadstudio.json --output out/drc.json
python scripts/cad_studio.py check-drc --input part.cadstudio.json --output out/drc.json --rule-pack drilling_panel --profile custom.json
```

MCP 提供 `cadstudio_list_drc_rules` 和 `cadstudio_check_drc`。前者返回规则、默认阈值与内置规则包；后者读取中性 JSON 和可选 `profile_paths`，写入不覆盖现有文件的版本化报告。报告写入属于写操作，严格的 MCP 审批模式仍要求批准。发现模式可搜索“设计规则审计”。

Profile 是只描述数据的 JSON，不执行代码。可通过 `thresholds` 调整已列出的阈值、`disabledRules` 停用规则，并用 `customRules` 添加受限字段比较。`holeEdgeDistanceRatio` 乘以**孔径**得到孔边到零件边的最小距离；`holeSpacingRatio` 乘以较大孔的**半径**得到中心距阈值，两者基准不同。例如孔径 6 mm、要求孔边距不少于 2 倍孔径时，配置 `holeEdgeDistanceRatio: 2.0`，对应最小边距 12 mm。规则包中的阈值只是初始建议，须按具体工况审查。

`status` 为 `fail` 表示发现规则失败，`warning` 表示发现警告；没有发现风险但有缺失或跳过的证据时为 `review_required`，CLI 返回 2。即便有通过项，也不代表未提供的证据合格；报告始终保留 `reviewRequired=true`。报告的风险分、条款说明和阈值不是安全认证或全面的标准符合性证明。

可传 `--baseline` 和 `--fail-on-regression` 比较设计变更。候选版本因缺少同类证据而使原问题消失时，门禁不会把它当作已修复。底层 `scripts/design_rule_check.py` 还支持带理由、责任人及有效日期的让步单；默认按当前 UTC 日期检查，过期或尚未生效的让步单不会应用。让步单不是独立审批或电子签名。

电机数据按 `metadata.drives[]` 提供，详情见 [drive-sizing.md](drive-sizing.md)。需要几何证据时，应先通过已验证的 SolidWorks 工作流读取模型并核对单位和语义；本 DRC 不会自动从活动模型补全所有参数。

实现参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)，感谢贡献者 geekx。
