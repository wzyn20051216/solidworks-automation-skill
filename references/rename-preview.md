# 基于自定义属性的改名预览（pilot）

此入口只读取文件级属性并生成改名计划，不重命名、移动或覆盖 SolidWorks 文件，也不更新装配体/工程图的外部引用。

```powershell
python scripts/sw_file_rename.py C:\work\parts --template "{图号}_{名称}" --output C:\work\rename-plan.json
```

模板只允许简单属性占位符；缺失属性、Windows 非法名称、已有文件名冲突和计划内重复名称均标为 `blocked`。输出报告独占创建，不覆盖现有文件，结果始终需要人工复核（CLI 退出码 2）。扫描为目录内的 SLDPRT、SLDASM、SLDDRW，不递归子目录，不跟随符号链接。

在 SolidWorks 2026 SP1.1 上，已验证单个零件的文件级属性读取、预览名称以及不关闭原先已打开的文档。多配置、复杂装配与图纸尚未真机验证。引用安全的批量实际改名仍未实现：不能用文件系统裸重命名代替 Pack and Go 及依赖核验。

此命令与公差提取、孔位分析真机入口共用进程间互斥锁；其他客户端、旧命令和手动操作不受此锁保护，应避免同时修改或关闭正在读取的文档。

实现方向参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。
