# 已显示尺寸公差提取（pilot）

`scripts/sw_tolerance_extract.py` 只读已保存的 SolidWorks 模型或图纸，提取当前配置的已显示尺寸、类型和公差边界到新的 CSV；不会修改模型，也不会覆盖已有文件。

```powershell
python scripts/sw_tolerance_extract.py C:\work\part.SLDPRT --output C:\work\tolerances.csv
```

报告始终是 `review_required`（命令行退出码 2）。当前仅在 SolidWorks 2026 SP1.1 的临时零件中实测线性尺寸和双向公差：`+0.10/-0.05 mm` 与 COM 直接回读一致。角度尺寸的弧度转度数有离线测试，装配体、工程图、角度和其他 SolidWorks 版本尚未真机验证。

- 只遍历当前配置已显示的尺寸；隐藏尺寸、其他配置和所有尺寸是否完整必须人工核对。
- 接口返回不可用、异常或非支持的类型时，记录未完成或跳过，绝不把缺失公差当作零。
- 线性尺寸使用 mm，角度尺寸使用度；不支持的尺寸种类跳过并提示。
- CSV 对可能触发公式的文本增加转义；用户打开前仍应检查来源。
- 命令采用受控 SolidWorks 会话；已有用户文档不会因本次读取被关闭。
- 本命令与改名预览、孔位分析真机入口共用进程间互斥锁；其他客户端、旧命令和手动操作不受此锁保护，应避免同时修改或关闭正在读取的文档。

实现思路参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。实际公差调用根据本地 2026 类型库和真机实测改写，`GetMinValue2` / `GetMaxValue2` 的返回值是状态码，实际边界从输出参数读取。
