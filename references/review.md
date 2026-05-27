# 结果自审查参考

## 必做检查

生成、修改或导出 SolidWorks 文件后，至少检查：

1. COM 调用返回值不是 `None`，关键特征对象创建成功。
2. `save_document()`、`session.save()`、`session.export()` 返回成功。
3. 输出 `.sldprt` / `.sldasm` / `.slddrw` / `.step` / `.stl` 等文件真实存在且大小合理。
4. 模型已重建：`model.ForceRebuild3(False)`。
5. 模型已缩放到适合窗口：`model.ViewZoomtofit2()`。
6. 至少导出一张等轴测 BMP，复杂模型导出前视、俯视、右视。

## 结构化自审查报告

```python
import sys
sys.path.insert(0, r"SKILL_DIR/scripts")

from sw_review import run_review

model.ForceRebuild3(False)
report, report_path = run_review(
    model,
    r"C:\temp\solidworks_review",
    basename="model",
    views=("isometric", "front", "top", "right"),
    expected_outputs=[r"C:\temp\model.sldprt", r"C:\temp\model.step"],
)
print(report_path)
print(report["checks"])
```

`run_review()` 会输出：

- 多视角 BMP 预览图。
- `*_review_report.json` 结构化报告。
- `evaluation.status`：`pass` / `warn` / `fail`。
- `evaluation.score`：规则评分，满分 100。
- `evaluation.issues`：机器可读的问题列表。
- `evaluation.recommendations`：修复建议。
- `checks.previews_created`：预览图是否生成。
- `checks.previews_not_blank`：预览图是否疑似非空白。
- `checks.expected_outputs_exist`：期望输出文件是否真实存在且大小大于 0。
- `checks.feature_summary_available`：是否能读取特征树摘要。

注意：结构化报告只能抓明显失败，不能替代人工或视觉模型对几何意图的判断。

## 命令行一键审查

```bash
python scripts/sw_review.py ^
  --file C:\temp\model.sldprt ^
  --output-dir C:\temp\solidworks_review ^
  --basename model ^
  --expected C:\temp\model.sldprt ^
  --expected C:\temp\model.step
```

返回码：

- `0`：`pass` 或 `warn`，报告已生成。
- `2`：`fail`，存在必须修复的问题。

## 目视自查清单

- 主体是否出现在画面中，是否为空白或只剩草图。
- 关键部件是否齐全，例如车轮、孔、轴、外壳、支架、BOM 表等。
- 比例是否明显错误，例如毫米误当米导致模型巨大。
- 方向是否正确，例如轮子是否在侧面而不是车顶。
- 部件是否明显重叠、悬空、穿模或缺少约束。
- 文件名、输出目录、导出格式是否符合用户要求。

## 发现问题时

1. 不要只报告“文件已保存”。
2. 先定位是草图、选择、拉伸方向、单位、基准面还是导出失败。
3. 修改脚本后重新生成并再次导出预览图。
4. 最终回复中说明已检查的预览图和仍有限制的地方。
