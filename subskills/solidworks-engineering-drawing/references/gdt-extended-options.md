# SW2026 扩展 GD&T 结构化输入

入口、源文件保护和保存重开规则见 [native-gdt.md](native-gdt.md)。这里的字段同时适用于
图纸副本计划与 DrawingSpec 的 `professionalAnnotations.geometricTolerances`，
通过既有 `solidworks_generate_drawing` MCP 工具执行，不新增工具。
旧单框字段和旧字母基准列表保持兼容。数值示例用于 API 回归，不能直接作为生产公差。

## 公共基准与子基准组

`datums` 最多包含三个按优先级排列的基准格；每格可为单个字母、带修饰的单个基准，
或一组公共基准。公共组写在同一格，不能用自由字符串 `"A-B"` 代替。

```json
{
  "datums": [
    {"common": ["A", {"label": "B", "materialCondition": "M"}],
     "subDatums": [["C", "D"]]},
    "E"
  ]
}
```

第一格表达 `A-B-(C-D)`，第二格为 E。每个成员必须对应实际存在或本计划声明的基准，
同一框中不得重复字母；公共组为 2..8 个成员，最多三个子基准组，每组 2..8 个成员。
各成员可独立指定 M/L/S。复合后续层只能保留前层完整基准格的前缀，不能拆散公共组。

单个基准还可以声明 `modifiers`；公共组成员也可使用这些字段：

```json
{"label": "A", "modifiers": {
  "situation": "plane", "section": "cross", "projection": "5", "freeState": true
}}
```

`situation` 为 `plane` / `straightLine` / `point`，`section` 为 `cross` / `longitudinal`，
`projection` 为明确的正十进制长度字符串（毫米），`freeState` 为布尔值。
整个基准格可指定 `constraints`：`translationX/Y/Z`、`rotationX/Y/Z`、`contactFeature`、
`orientationOnly`、`variableDistance` 是约束开关；`translation` 为三个有符号十进制字符串组成的 I/J/K 分量。
这些是公差框要求，不会移动模型。约束适用性仍由设计者确认。

## 公差层选项

旧单框的 `options` 直接放在该公差项；多框时放在每个 `frames[]` 内。
不能同时提供 `frames` 和顶层单框 `options`。

| options 字段 | 结构与含义 |
|---|---|
| `projectedZone` | `{"projection":"12","range":"4"}`；主投影长度必填，范围可选，均为正毫米字符串。目前用于圆柱位置度或轴线方向公差。 |
| `profileZone` | 轮廓不等分布、偏置、CZ/SZ、动态轮廓和公差带约束，见下方。 |
| `zoneShape` | `none` / `diameter` / `sphericalDiameter` / `square`；圆柱/球形直径须与 `diameter:true` 一致。复合层不能改变形状。 |
| `unitZone` | `separator`（`/` 或 `-`）、正 `value`、可选 `symbol`；可追加 `limit:{separator,value,symbol}`，第二分隔为 `X` 或 `-`。 |
| `maxTolerance` | `{"value":"0.5","diameter":true}`；最大公差不得小于主公差。 |
| `reciprocity` | 互易要求开关；启用时必须同时声明公差本体 `materialCondition:"M"` 或 `"L"`。 |
| `freeState` / `statistical` | 公差本体的自由状态、统计公差开关，与基准成员的自由状态分别表达。 |
| `symbolLibrary` | `iso` / `asme` / `gb`，分别映射 IGTOL / GTOL / GGTOL。默认保持旧 ISO 库；复合层不得改变符号库。 |
| `associatedFeature` | Minimax / LeastSquares / MinimumCircumscribed / Tangent / MaximumInscribed。 |
| `derivedFeature` | 尺寸要素导出特征开关。 |
| `associatedCharacteristic` | C / CE / CI / G / GE / GI / X / N。 |
| `parametricCharacteristic` | P / V / T / Q。 |
| `filters` | 1..8 项显式滤波配置，见下方。 |

`unitZone.symbol` 与 `limit.symbol` 允许 `none`、`diameter`、`sphericalDiameter`、`square`、`angle`。
公差、长度、偏置、滤波截止值使用非指数十进制字符串，最多 32 个字符；拒绝 NaN、Infinity、
指数形式和未支持字段。负数仅用于明确允许的平移分量，偏置正负由 `direction` 指定。
公差本体材料条件仍沿用原生入口已验证的范围；Schema 接受不等于标准或几何适用性已经证明。

### 轮廓与公差带

```json
{"options": {"profileZone": {
  "offsets": [{"direction":"outside","value":"0.1"},
              {"direction":"inside","value":"0.05"}],
  "dynamic": true, "combination":"CZ",
  "constraints":["offset","angularOffset","orientationOnly"]
}}}
```

不等分布使用 `unequalOutside:"0.05"`，不得超过总公差；它与 `offsets` 互斥。
`offsets` 为一或两项，方向为 `outside` 或 `inside`。不等分布、偏置、动态轮廓要求使用线轮廓度或面轮廓度。
`combination` 为 `CZ` 或 `SZ`；三个公差带约束不得重复。组合和约束可单独声明。

### 滤波

```json
{"options": {"filters": [{
  "symbol":"G", "cutOff":"0.8", "shortWave":true,
  "separator":"X", "second":{"cutOff":"2.5","longWave":true}
}]}}
```

每项必须提供滤波符号和正 `cutOff`，可选 `shortWave` / `longWave`。
符号白名单为 G/S/SW/CW/RG/RS/OB/OH/OD/CB/CH/CD/AB/AH/AD/F/H。
第二段具有自己的截止值和开关，双段必须显式指定 `separator:"Space"` 或 `"X"`。

## SW2026 实测格式差异与验收

公开帮助和安装 XSD 是查证起点，实际接口并非逐字遵循它们。本机 SW2026 SP1.1 已确认：

- CZ/SZ 原生界面回读使用 `CombinationSymbol`，公开 XSD 的 `Combination` 会被接口静默丢弃。
- 基准截面标志在实际回读中排在其他成员修饰之后。
- 局部范围会补齐空的范围符号节点；`false` 缺省节点则被省略。

生成器按已验证的原生形式构建 XML，并继续严格核对全部节点、值和顺序，
不会通过忽略差异来隐藏选项丢失。失败报告指出首个差异路径，缺失/改变公共组成员、
投影长度、材料条件或 CZ/SZ 都不能通过审查。未知选项在连接 CAD 前阻断，不回退为普通 Note。

真机矩阵只使用自建测试件，逐例核对原生写入、保存重开、持久关联、PDF/BMP 与源哈希，
并检查实际显示的 A-B、子基准组、P 长度、轮廓偏置和 CZ/SZ。
稀有组合矩阵用于 API 验证，可能故意将很多符号放在同一测试位置，不作为可制造图纸交付。
完整自动落图样例还必须通过 PDF/布局检查和目视复核。

```powershell
python -m pytest -q tests/test_sw_gdt_options.py tests/test_sw_gdt_annotation.py tests/test_sw_gdt_copy.py tests/test_sw_drawing_native.py
python tests/solidworks_gdt_extended_live.py --source C:\test\self-created.slddrw --plan C:\test\gdt-plan.json
python tests/solidworks_gdt_generation_live.py --source C:\test\self-created-plate.sldprt --extended-gdt --mcp
```

真机和 `test_sw_read_guard` 不并行执行。输出继续保持 `review_required`，
本功能表达用户给定要求，不自动证明任意参数组合符合制造标准。
