# 工程图生成参考

## 标准

GB/T 路线默认第一角投影：俯视位于主视下方，右视位于主视左侧。SolidWorks 的
`SetupSheet6` / `NewSheet4` 投影参数必须和布局保持一致，并在生成后回读。

## 证据要求

- 视图对象、方向、位置和比例必须回读。
- `InsertModelAnnotations3/4` 返回值不能单独作为尺寸已插入证据，必须再次读取真实 `DisplayDimension`。
- 图框文件名只代表候选证据，不能证明模板内容符合 GB/T。
- PDF/BMP 输出必须存在且非空；PDF 文字边界只能用于风险筛查。

## API 规则

新增或未封装的 SolidWorks API 先查 `references/api-lookup.md` 和官方 API Help，确认签名、
枚举、返回值和版本差异后再实现。COM 返回 `None` 或 `False` 时返回明确状态，不伪造成功。

