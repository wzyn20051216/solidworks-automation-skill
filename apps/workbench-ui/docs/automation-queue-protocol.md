# CAD Studio 本地自动化队列协议

## 目标

CAD Studio 桌面端通过 Tauri 把任务保存为本机 JSON 文件，Python worker 读取队列并执行。第一版 worker 使用 mock handler，后续把 handler 替换为 SolidWorks / AutoCAD 自动化即可。

## 队列目录

Rust 侧以 `app.path().app_data_dir()/queue` 为准。当前 Tauri 标识为:

```text
com.wzyn.cadstudio
```

Windows 常见路径:

```text
%APPDATA%\com.wzyn.cadstudio\queue
```

worker 默认也会读取该目录。调试时可以显式指定:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --queue-dir "<队列目录>"
```

持续监听:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<队列目录>"
```

## 任务 JSON

每个任务一个文件，文件名来自安全化后的 `id`:

```text
{id}.json
```

字段:

```json
{
  "id": "job-1721900000000-a1b2c3",
  "kind": "create_shell",
  "title": "新建外壳",
  "detail": "生成参数化壳体、开孔和基础检查任务",
  "status": "queued",
  "progress": 0,
  "createdAt": "2026-07-25T12:00:00.000Z",
  "updatedAt": "2026-07-25T12:00:00.000Z",
  "projectPath": "D:/demo/demo_shell.step"
}
```

任务类型:

- `create_shell`: 新建参数化外壳、开孔和基础检查。
- `import_model`: 导入本地 CAD 模型并建立项目上下文。
- `delivery_package`: 生成 STEP、STL、PDF、DWG 等交付包。

状态流转:

```text
queued -> running -> passed
queued -> running -> failed
queued -> cancelled
```

约定:

- UI 只创建任务和取消任务。
- worker 只处理 `status == "queued"` 的任务。
- `passed`、`failed`、`cancelled` 是终态。
- worker 回写 `workerLog`、`lastMessage`、`result` 或 `error`，前端可以直接展示这些字段。
- 真实 CAD handler 必须在写入 `passed` 前完成文件存在性检查，不能把占位文件标为可制造交付。

## 接入真实执行器

Python worker 的扩展点在:

```text
apps/desktop/cad_workbench/queue_worker.py
```

替换或注入 handler:

- `create_shell` -> SolidWorks 建模、实体开孔、STL/STEP 导出。
- `import_model` -> 文件解析、缩略图、项目目录初始化。
- `delivery_package` -> AutoCAD 图纸导出、PDF/DWG/DXF、交付清单和规范复核。

执行器必须遵守 P0 门禁:

- 3D 打印开孔必须是真实几何切除，不允许只画线或只写注释。
- 图纸必须保留完整尺寸链、孔表、技术要求、图框标题栏和 GB/T 风格标注。
- 失败时写回 `failed` 和明确 `error`，不要静默跳过。
