"""基于实际 MCP 工具元数据的离线检索；不承担授权和执行。"""
from __future__ import annotations

import copy
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any


# 每组代表一个概念；同组中多个词命中只加一次分，避免格式/同义词堆叠。
_CONCEPTS: tuple[tuple[str, ...], ...] = (
    # 建模特征
    ("干涉检查", "检查干涉", "干涉检测", "干涉", "interference"),
    ("拉伸凸台", "凸台拉伸", "草图拉伸", "草图", "拉伸", "extrude", "extrusion", "sketch"),
    ("切除", "挖孔", "cut"),
    ("圆角", "倒圆", "fillet"),
    ("倒角", "chamfer"),
    ("旋转特征", "旋转体", "旋转", "revolve"),
    ("抽壳", "空心", "shell", "hollow"),
    ("阵列", "pattern"),
    ("镜像", "mirror"),
    ("孔特征", "打孔", "开孔", "钻孔", "异型孔", "hole feature", "hole", "counterbore", "countersink"),
    ("孔检查", "检查孔", "孔位", "hole inspection", "inspect hole"),
    ("审视模型", "审视当前模型", "模型审视", "review active", "review the active"),
    # 查询与测量
    ("质量属性", "质量特性", "质心", "质量", "mass properties", "centre of mass", "center of mass"),
    ("包围盒", "边界框", "外廓尺寸", "bounding box"),
    ("边线", "边缘", "edges", "list edges"),
    ("文档单位", "单位设置", "单位", "units", "unit system"),
    ("自定义属性", "文件属性", "custom properties"),
    ("配置族", "配置", "configuration"),
    ("更改尺寸", "修改尺寸", "更新尺寸", "改尺寸", "命名尺寸", "尺寸", "update dimension", "dimension"),
    ("外观颜色", "外观", "颜色", "着色", "appearance", "color"),
    ("预览", "preview"),
    # 文档与文件
    ("新建文档", "新建零件", "新建装配", "新建工程图", "新建", "new document", "new part", "new assembly", "new drawing"),
    ("基础零件", "圆柱", "立方体", "方块", "basic part", "cylinder"),
    ("打开文件", "打开文档", "打开", "open document", "open file"),
    ("保存文件", "保存文档", "保存", "另存为", "save document", "save as", "save"),
    ("关闭文档", "关闭", "close document", "close"),
    ("打包", "pack and go", "pack"),
    ("导出", "输出文件", "export"),
    ("批量导出", "批量输出", "batch export"),
    ("材料清单", "物料清单", "明细表", "bom"),
    ("设计规格", "规格文件", "规格", "design spec", "spec file", "build from spec", "spec"),
    # 装配
    ("装配体", "装配", "assembly"),
    ("添加零件", "添加组件", "插入零件", "装配零件", "add component", "insert component"),
    ("固定组件", "浮动组件", "固定住", "固定", "浮动", "component fixed", "fixed component",
     "set component fixed", "fix component", "float component"),
    ("同心配合", "同轴配合", "concentric mate", "concentric"),
    ("重合配合", "重合", "coincident mate", "coincident"),
    ("距离配合", "间距配合", "distance mate", "distance"),
    ("替换组件", "替换零件", "replace component"),
    ("排除实体", "删除实体", "排除", "exclude bodies", "exclude body"),
    # 工程图
    ("工程图", "图纸", "drawing"),
    ("生成工程图", "创建工程图", "出工程图", "create drawing", "generate drawing"),
    ("审视工程图", "审查工程图", "检查工程图", "review drawing"),
    ("读取工程图", "工程图结构", "视图结构", "inspect drawing"),
    # 运动
    ("运动算例", "运动研究", "motion study"),
    ("旋转马达", "旋转电机", "马达", "motor", "rotary motor"),
    ("运动检查", "检查运动算例", "inspect motion", "motion audit"),
    ("验证运动", "运动验证", "validate motion"),
    # 分析
    ("有限元", "有限元分析", "fea", "finite element"),
    ("有限元预检", "求解器检查", "求解器", "fea preflight", "solver"),
    ("准备有限元", "准备分析", "生成inp", "fea prepare", "prepare fea", "calculix"),
    ("运行有限元", "跑有限元", "求解", "fea run", "run fea"),
    ("收敛", "convergence"),
    ("制造性检查", "可制造性", "制造性", "制造检查", "加工", "machining", "dfm"),
    ("设计规则", "设计审计", "设计检查", "电机选型", "扭矩核验", "design audit", "design rules", "motor sizing", "drc"),
    ("高级几何", "曲面审查", "advanced geometry"),
    ("放样", "loft"),
    ("曲面", "加厚", "knit", "thicken", "surface"),
    # 线缆与路由
    ("线缆", "布线", "管路", "routing", "cable"),
    ("布线检查", "管路检查", "routing review"),
    ("布线预检", "routing preflight"),
    # 环境与服务
    ("连接软件", "连接solidworks", "连接", "connect solidworks", "connect"),
    ("接口查证", "查询api", "api文档", "接口签名", "接口参数", "api lookup", "api signature", "lookup api"),
    ("版本信息", "版本号", "版本", "revision", "version", "solidworks version"),
    ("当前文档", "活动文档", "打开的文档", "已打开的文档", "文档列表", "文档状态",
     "open documents", "active document status", "document status", "current document"),
    ("健康检查", "环境诊断", "依赖检查", "health check"),
    ("恢复", "卡住", "卡死", "recover", "blocked"),
    ("后端选择", "后端", "语言后端", "语言", "backend", "language backend"),
    ("插件状态", "插件", "加载项", "addin", "add-in"),
    ("原生几何", "实体名称", "native geometry"),
    ("圆截面扫描", "扫描", "圆截面", "sweep", "sweeps", "round sweep", "round sweeps"),
    ("导入step", "导入零件", "import step", "import part"),
    ("开放格式", "写出step", "写出", "写一个", "write out", "write open format", "open format"),
    ("dxf预览", "预览场景", "preview scene", "dxf preview"),
    ("读取产物", "取回产物", "取回", "产物", "artifact"),
    # 文件格式
    ("step", "stp"),
    ("iges", "igs"),
    ("stl",),
    ("pdf",),
    ("dxf",),
)

_WORDS = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)

# 用户说"查看/检查"时要的是读工具，"创建/导出"时要的是写工具；这条只做小幅加减，
# 让意图与概念证据冲突时偏向用户真正想做的动作。
_READ_INTENT = (
    "查看", "检查", "读取", "审视", "审查", "列出", "获取", "查询", "哪些", "有没有",
    "是否", "多少", "list", "inspect", "check", "read", "review", "show", "query", "get",
)
_WRITE_INTENT = (
    "创建", "新建", "添加", "生成", "导出", "保存", "修改", "更新", "设置", "删除", "关闭",
    "替换", "导入", "画", "写入", "运行", "打包", "切换", "加上", "加重", "改成", "建模",
    "write", "create", "add", "generate", "export", "save", "update", "set", "delete",
    "close", "replace", "import", "run", "build", "pack", "activate", "fix",
)
_READ_VERBS = frozenset({
    "inspect", "list", "check", "validate", "review", "preflight", "status", "read",
    "resolve", "health", "audit", "describe", "search",
})


def _is_read_like(tool_name: str) -> bool:
    # 动词可能不在名称首位（如 interference_check），逐个词判断更稳。
    return any(part in _READ_VERBS for part in tool_name.split("_")[1:])


# 只有通用动作、没有 CAD 对象的查询（如"打开微信"）不应命中任何工具；
# 这些动作词只有和对象词同时出现时才作为证据。
_OBJECTS = (
    "文档", "文件", "零件", "装配", "工程图", "图纸", "模型", "实体", "特征", "草图",
    "配置", "尺寸", "材料", "属性", "视图", "组件", "马达", "算例", "求解器", "线缆",
    "管路", "曲面", "表面", "路径", "bom",
)
_GENERIC_ACTION_GROUPS = frozenset({
    "打开文件", "保存文件", "关闭文档", "新建文档", "预览",
})


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _contains(text: str, term: str) -> bool:
    term = _normalize(term)
    if not term:
        return False
    if re.search(r"[\u3400-\u9fff]", term):
        return term in text
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _metadata(tool: Any) -> dict[str, Any]:
    if isinstance(tool, Mapping):
        value = dict(tool)
    elif hasattr(tool, "model_dump"):
        value = tool.model_dump(by_alias=True, exclude_none=True)
    else:
        raise TypeError("工具元数据必须为字典或 MCP 工具对象")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("工具名称必须是非空字符串")
    # FastMCP 的 Tool 内部字段叫 parameters，协议字段叫 inputSchema，统一成一个。
    if "inputSchema" not in value and "parameters" in value:
        value["inputSchema"] = value.pop("parameters")
    return copy.deepcopy(value)


class ToolCatalog:
    """一次从注册表构建快照；工具列表更新时由调用方重新构建。"""

    def __init__(self, tools: Sequence[Any], *, read_names: Collection[str] | None = None):
        self._tools: dict[str, dict[str, Any]] = {}
        self._name: dict[str, str] = {}
        self._text: dict[str, str] = {}
        # 由策略层提供读写分级时以它为准；否则退回按名称动词猜测。
        self._read_names = None if read_names is None else frozenset(read_names)
        for item in tools:
            tool = _metadata(item)
            name = tool["name"]
            if name in self._tools:
                raise ValueError(f"重复的工具名称: {name}")
            self._tools[name] = tool
            self._name[name] = _normalize(name)
            self._text[name] = _normalize(
                " ".join(str(tool.get(k) or "") for k in ("name", "title", "description"))
            )

    def describe(self, name: str) -> dict[str, Any] | None:
        """返回独立副本，保留完整 Schema 和原始注解；未知名称返回 None。"""
        item = self._tools.get(name)
        return copy.deepcopy(item) if item is not None else None

    def _is_read(self, name: str) -> bool:
        if self._read_names is None:
            return _is_read_like(name)
        return name in self._read_names

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """返回紧凑候选；名称必须由调用方进一步校验及授权后才能执行。"""
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError("检索内容须为 1 至 512 字符")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("结果数量须为 1 至 20 的整数")
        q = _normalize(query)
        groups = [group for group in _CONCEPTS if any(_contains(q, term) for term in group)]
        if not any(_contains(q, term) for term in _OBJECTS):
            groups = [group for group in groups if group[0] not in _GENERIC_ACTION_GROUPS]
        words = {w for w in _WORDS.findall(q) if len(w) >= 2}
        # 产品名出现在大多数工具名中，不应让它压过已识别的具体操作概念。
        if groups:
            words.discard("solidworks")
        # 只有单向意图才加权；"检查并修复"这类混合诉求不猜方向。
        read_intent = any(_contains(q, term) for term in _READ_INTENT)
        write_intent = any(_contains(q, term) for term in _WRITE_INTENT)
        intent = 0 if read_intent == write_intent else (1 if read_intent else -1)
        matches: list[tuple[int, str]] = []
        for name, text in self._text.items():
            normalized_name = self._name[name]
            score = 1000 if q == normalized_name else 0
            # 工具名命中比说明命中更有判别力：中文命令名多数只出现在名字里。
            if len(q) >= 3 and _contains(normalized_name, q):
                score += 30
            elif len(q) >= 3 and _contains(text, q):
                score += 20
            # 每个概念组最多加一次分，避免同义词堆叠刷分。
            for group in groups:
                if any(_contains(normalized_name, term) for term in group):
                    score += 18
                elif any(_contains(text, term) for term in group):
                    score += 8
            for word in words:
                if _contains(normalized_name, word):
                    score += 6
                elif _contains(text, word):
                    score += 1
            # 产品名仅用于已有匹配证据的候选排序，不能单独召回无关工具。
            if groups and score and _contains(q, "solidworks") and _contains(normalized_name, "solidworks"):
                score += 1
            # 只调整已有证据的候选，避免纯靠意图把无关工具拉进结果。
            if score and intent:
                score += 6 if self._is_read(name) == (intent > 0) else -6
            if score:
                matches.append((score, name))
        matches.sort(key=lambda item: (-item[0], item[1]))
        result = []
        for score, name in matches[:limit]:
            description = str(self._tools[name].get("description") or "").strip().split("\n", 1)[0]
            result.append({"name": name, "description": description[:240], "score": score})
        return result
