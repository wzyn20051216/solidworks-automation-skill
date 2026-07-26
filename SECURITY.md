# 安全策略

## 支持版本

安全修复优先覆盖 GitHub Releases 中最新的 CAD Studio 版本和 `main` 分支。

## 报告漏洞

请使用 GitHub Security Advisory 私下报告可能导致凭据泄露、任意文件写入、命令注入、审批绕过或不受控 CAD 自动化的问题。不要在公开 Issue 中附带 API Key、公司图纸、任务队列或完整日志。

## 信任边界

- CAD Studio 不保存 AI API Key；认证由 Agent CLI 或 CC Switch 管理。
- CAD、跨目录、网络、删除和 Git 推送属于危险能力，必须经过策略门禁。
- AI 输出不能替代机械工程师的尺寸、材料、载荷、安全和制造复核。
- 官方开源构建目前未提供商业代码签名，下载后应核对 GitHub Release SHA-256。
