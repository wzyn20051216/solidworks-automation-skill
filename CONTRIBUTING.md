# 贡献指南 / Contributing Guide

感谢你对 SolidWorks Automation Skill 项目的关注!

## 如何贡献

### 报告 Bug

如果你发现了 Bug,请创建一个 Issue 并包含以下信息:

- SolidWorks 版本
- Python 版本
- 操作系统版本
- 详细的错误信息和堆栈跟踪
- 重现步骤

### 提交功能请求

如果你有新功能的想法:

1. 先检查 Issues 中是否已有类似请求
2. 创建新 Issue 描述你的想法
3. 说明使用场景和预期效果

### 提交代码

1. **Fork 仓库**
   ```bash
   git clone https://github.com/yourusername/solidworks-automation-skill.git
   cd solidworks-automation-skill
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **编写代码**
   - 遵循现有代码风格
   - 添加必要的注释(中文)
   - 确保代码在 SolidWorks 2020-2025 上都能运行

4. **测试**
   - 在 SolidWorks 中测试你的代码
   - 确保没有破坏现有功能

5. **提交**
   ```bash
   git add .
   git commit -m "添加: 你的功能描述"
   ```

6. **推送并创建 PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   然后在 GitHub 上创建 Pull Request

## 代码规范

### Python 代码风格

- 使用 4 个空格缩进
- 函数和变量使用 snake_case
- 类名使用 PascalCase
- 常量使用 UPPER_CASE
- 中文注释和文档字符串

### 文档规范

- 所有公共函数必须有文档字符串
- 文档字符串使用中文
- 包含参数说明和返回值说明

示例:
```python
def extrude_boss(model, sketch_name, depth, direction=True, merge=True):
    """
    凸台拉伸

    参数:
        model: IModelDoc2
        sketch_name: 草图名称(如 "Sketch1")
        depth: 拉伸深度(米)
        direction: True=正方向
        merge: True=合并结果

    返回:
        IFeature 对象
    """
    # 实现代码...
```

### 提交信息规范

使用中文,格式如下:

- `添加: 新功能描述`
- `修复: Bug 描述`
- `更新: 更新内容描述`
- `文档: 文档更新描述`
- `重构: 重构内容描述`

## 项目结构

```
solidworks-automation-skill/
├── scripts/              # 核心 Python 模块
│   ├── sw_connect.py    # 连接和文档管理
│   ├── sw_part.py       # 零件建模 API
│   ├── sw_assembly.py   # 装配体 API
│   ├── sw_drawing.py    # 工程图 API
│   └── sw_export.py     # 文件导出 API
├── references/          # API 参考文档
├── examples/            # 示例代码
├── README.md            # 项目说明
└── CONTRIBUTING.md      # 本文件
```

## 添加新功能

如果你想添加新的 API 封装:

1. 在对应的 `scripts/sw_*.py` 文件中添加函数
2. 在 `references/` 中更新相关文档
3. 在 `examples/` 中添加使用示例
4. 更新 README.md

## 需要帮助?

- 查看 [references/](./references/) 目录下的文档
- 查看 [examples/](./examples/) 目录下的示例
- 在 Issues 中提问
- 参考 [SolidWorks API 官方文档](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks_namespace.html)

## 行为准则

- 尊重所有贡献者
- 保持友好和专业
- 接受建设性的批评
- 关注对项目最有利的事情

感谢你的贡献! 🎉
