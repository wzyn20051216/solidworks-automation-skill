# 示例代码

本目录包含 SolidWorks 自动化的示例代码,从基础到高级逐步演示各种功能。

## 示例列表

### 01_basic_part.py
创建基本零件 - 圆柱体

**学习内容:**
- 连接 SolidWorks
- 创建新零件文档
- 绘制草图(圆)
- 拉伸特征
- 保存文件

**运行前提:**
- SolidWorks 已运行
- 确保 `C:\temp\` 目录存在

---

### 02_complex_part.py
创建复杂零件 - 带孔的矩形板

**学习内容:**
- 多个草图和特征
- 切除拉伸(孔)
- 倒角和圆角
- 面选择

**运行前提:**
- SolidWorks 已运行

---

### 03_assembly.py
创建装配体

**学习内容:**
- 添加组件
- 配合关系(重合、同心)
- 获取组件列表

**运行前提:**
- 需要准备两个零件文件:
  - `C:\parts\base.sldprt`
  - `C:\parts\shaft.sldprt`
- 或修改代码中的路径

---

### 04_batch_export.py
批量导出文件

**学习内容:**
- 批量处理文件
- 导出为 STEP 格式
- 错误处理

**运行前提:**
- `C:\parts\` 目录下有 .sldprt 文件
- 或修改代码中的路径

---

### 05_drawing.py
创建工程图

**学习内容:**
- 创建工程图文档
- 标准三视图
- 自动标注尺寸
- 添加注释
- 导出 PDF

**运行前提:**
- 需要一个零件文件: `C:\parts\mypart.sldprt`
- 或修改代码中的路径

---

## 运行示例

1. 确保已安装依赖:
```bash
pip install pywin32
```

2. 启动 SolidWorks

3. 运行示例:
```bash
python 01_basic_part.py
```

## 修改路径

所有示例中的文件路径都可以根据你的实际情况修改:

```python
# 修改输入路径
part_path = r"C:\your\path\part.sldprt"

# 修改输出路径
output_path = r"C:\your\output\file.step"
```

## 常见问题

### 无法连接 SolidWorks?
确保 SolidWorks 已经运行,并且 Python 位数与 SolidWorks 一致(通常为 64 位)。

### 找不到基准面?
中英文版本的基准面名称不同:
- 英文: "Front Plane", "Top Plane", "Right Plane"
- 中文: "前视基准面", "上视基准面", "右视基准面"

### 特征创建失败?
检查:
1. 草图是否闭合
2. 单位是否正确(使用 `mm()` 函数)
3. 实体选择是否正确

更多问题请查看 [troubleshooting.md](../references/troubleshooting.md)
