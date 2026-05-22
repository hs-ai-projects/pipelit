---
name: using-pipelit
description: Pipelit 路由指南。不确定用哪个 skill 时自动激活。包含各 skill 触发场景和 L1/L2/L3 任务分级规则。
---

# Pipelit — 使用指南

Pipelit 是 AI 研发流程自动化插件集，覆盖飞书任务、版本发布、代码提交等高频研发场景。

## Skill 速查

| Skill | 触发词 | 适用场景 |
|-------|--------|---------|
| `feishu-dev` | 飞书任务 ID / URL、"帮我完成飞书任务"、"列出飞书任务"、`/feishu-dev` | 飞书任务全链路：查询、L2 开发、L3 分析 |
| `feishu-commit` | `/feishu-commit <task_id>`、"带飞书链接提交" | 普通 commit，自动注入飞书任务链接 |
| `release` | "发版"、"打 tag"、"release"、"准备上线" | 版本发布全流程 |
| `changelog` | "changelog"、"更新日志"、"发版说明" | 生成版本更新文档 |
| `guance-log-analysis` | "观测云"、"查日志"、"查报错"、"接口报错"、"分析错误"、"guance logs" | 观测云 ads-backend 错误日志分析 |

## 任务分级（L1 / L2 / L3）

收到任务时，先判断级别，再选择对应路径：

### L1 — 低风险，直接执行

**特征：** 不改业务逻辑，输出可预期，失败影响小

- 生成 commit message
- 更新版本号
- 生成 changelog / release note
- 纯文档修改

**路径：** `/feishu-commit` 或 `/release`，一键执行，不需要 Plan

---

### L2 — 中等风险，先 Plan 再执行

**特征：** 改代码，但范围清晰，≤ 3 个文件，逻辑独立

- 普通 bug 修复（有截图/报错/日志）
- 小需求（加字段、改交互、新增接口）
- 配置调整

**路径：** 说飞书任务 ID 或 `/feishu-dev`，feishu-dev 自动识别为 L2
**规则：** AI 给出实现计划 → 用户确认 → 执行 → 确认后 push

---

### L3 — 高风险，只分析不执行

**特征：** 影响范围大，逻辑复杂，或不确定改动是否安全

- 架构调整、模块重构
- 复杂跨模块 bug
- 线上事故排查
- 涉及文件 > 5 个

**路径：** 说飞书任务 ID 或 `/feishu-dev`，feishu-dev 自动识别为 L3
**规则：** 输出分析报告（定位、原因、拆分建议），不改代码，不 commit

---

## 快速判断

```
飞书任务 ID / URL                → feishu-dev（自动判断 L2 或 L3）
改动文件 ≤ 3，需求清晰           → feishu-dev 走 L2 完整开发流程
改动文件 > 5，或逻辑复杂         → feishu-dev 走 L3 只输出分析报告
只生成文本/更新配置/写 changelog  → release 或 feishu-commit（L1）
```

## 配置文件

| 配置文件 | 位置 | 用途 |
|---------|------|------|
| `~/.claude/plugins/cache/pipelit/config.json` | 全局，自动生成 | 飞书凭据、feishu-dev 项目路径 |
| `.claude/release-config.json` | 项目内，首次发版时生成 | 仓库路径、版本文件、changelog 选项 |
