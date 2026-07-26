# 企业 Agent 与机械知识库

## 目标架构

CAD Studio 采用“控制平面 + 确定性 CAD 工具 + Reviewer Gate + 本地优先 RAG”的结构：

```text
用户对话/UI 配置
  -> Intake / Planner
  -> 本地知识检索（默认）
  -> 可选云知识检索（显式启用 + 外部网络审批）
  -> Codex Executor
  -> SolidWorks / AutoCAD 串行工具
  -> Artifact Ledger
  -> Reviewer Gate
  -> 人工复核与继续对话
```

`apps/desktop/cad_workbench/knowledge_retrieval.py` 已实现：

- 检索主 `SKILL.md`、`references/`、所有子技能参考资料和知识文件。
- 中英文词元检索、分块、Top-K 排序。
- 每个片段返回来源路径、内容 SHA-256、评分和 provider。
- Worker 自动把检索结果注入企业 Prompt。
- 可选 HTTPS 云 RAG 连接器，令牌只从环境变量读取。

## 数据边界

1. 默认只检索本地 Skill 知识，不上传用户工程、模型、图纸或 Prompt。
2. 云知识库必须在任务中显式声明 `external_network`，并完成人工审批。
3. 云端 endpoint 必须是 HTTPS；Token 不写入任务 JSON、日志或 UI 持久化文件。
4. Token 环境变量固定为 `CAD_STUDIO_RAG_TOKEN`；任务不能指定其它环境变量名，避免读取并外发无关凭据。
5. 自定义本地知识目录会触发跨工作区访问审批；直接写队列文件也不能绕过该门禁。
6. 检索片段只能作为参考证据，不能替代 GB/T、ISO、材料手册、供应商目录或企业标准原文。
7. 知识片段必须保留 `source` 与 `sha256`；无法追溯来源的内容不得作为制造门禁依据。

## 任务配置

```json
{
  "uiConfig": {
    "knowledgeBase": {
      "topK": 6,
      "localRoots": ["D:/company-cad-standards"],
      "cloudEnabled": false,
      "endpoint": "https://rag.example.com/retrieve",
      "namespace": "mechanical-engineering",
      "tokenEnv": "CAD_STUDIO_RAG_TOKEN"
    }
  }
}
```

云服务响应契约：

```json
{
  "chunks": [
    {
      "title": "轴承座孔配合",
      "source": "enterprise-standard://bearing/fit-v3",
      "text": "可检索的原文片段",
      "score": 0.91
    }
  ]
}
```

## 知识库分层

- `L0 会话事实`：用户尺寸、用途、材料、载荷、制造方式、目标软件。
- `L1 项目知识`：当前工程图、参数表、BOM、企业标准、历史修订。
- `L2 技能知识`：本仓库参考文档、专项子技能、已验证 API 经验。
- `L3 组织知识`：经批准的模板、失败案例、工艺能力、供应商约束。
- `L4 外部知识`：官方 API、国家/行业标准、厂商手册；必须保留版本和来源。

检索优先级为 `L0 > L1 > L2 > L3 > L4`。发生冲突时停止自动执行并把冲突交给 Reviewer，不允许静默选择。

## 上云前门禁

- 多租户 namespace 隔离与最小权限 Token。
- 文档级 ACL 在检索前执行，不能只在生成答案后过滤。
- 上传、删除、重建索引均有不可变审计记录。
- PII、密钥、客户图纸水印和受控技术资料在客户端脱敏。
- 支持来源撤销、版本回滚、过期策略和引用命中统计。
- 对标准号、材料、公差和安全系数建立“需原文复核”标签。
