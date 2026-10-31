# 基于自定义属性的改名预览（pilot）

此入口只读取文件级属性并生成改名计划，不重命名、移动或覆盖 SolidWorks 文件，也不更新装配体/工程图的外部引用。

```powershell
python scripts/sw_file_rename.py C:\work\parts --template "{图号}_{名称}" --output C:\work\rename-plan.json
```

模板只允许简单属性占位符；缺失属性、Windows 非法名称、已有文件名冲突和计划内重复名称均标为 `blocked`。输出报告独占创建，不覆盖现有文件，结果始终需要人工复核（CLI 退出码 2）。扫描为目录内的 SLDPRT、SLDASM、SLDDRW，不递归子目录，不跟随符号链接。

在 SolidWorks 2026 SP1.1 上，已验证单个零件的文件级属性读取、预览名称以及不关闭原先已打开的文档。扫描时会跳过 `~$` 开头的 SolidWorks 临时锁文件。

## 把独立零件复制为新名称

对已保存的 SLDPRT，若读取到的配置只有一个、实体只有一个，且依赖清单、普通外部引用计数与辅助外部引用计数均为空，可将预览计划复制到**尚不存在的新目录**：

```powershell
python scripts/sw_rename_copy.py --plan C:\work\rename-plan.json --output-dir C:\work\new-copies
```

新文件通过独占创建和逐字节复制生成；每项核对源文件与副本的 SHA-256，再用 SolidWorks 重开检查体积、包围盒和实体数量。源文件保留不动，输出 `copy-manifest.json`，结果仍为 `review_required`（CLI 退出码 2）。遇到失败立即停止，已经创建的文件和清单保留供排查，不自动删除或重试。目录必须不存在，父目录必须已经存在。一次最多 100 个零件。

此入口不处理装配体、工程图、多配置、多个实体或检测到外部引用的零件，也不会更新其他文件对源零件的引用。检查结果为空不证明不存在所有潜在引用，复制后仍需工程师确认；尤其不能把它当作装配体的引用安全改名。SW2026 SP1.1 已完成两零件的属性预览、原文件哈希、复制和重开验证，其他版本尚未真机验证。

使用独立副本而非原位重命名，是因为本机 SW2026 测试中，`SavePackAndGo` 在只读打开的零件上仍改变了测试源文件；装配体的 Pack and Go 清单也未列出实际存在的两个组件。因此涉及引用的批量改名仍保持阻断。参考官方 [`GetDependencies2`](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~GetDependencies2.html) 和 [`ListExternalFileReferencesCount`](https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDocExtension~ListExternalFileReferencesCount.html) 文档。

此命令与公差提取、孔位分析真机入口共用进程间互斥锁；其他客户端、旧命令和手动操作不受此锁保护，应避免同时修改或关闭正在读取的文档。

实现方向参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。
