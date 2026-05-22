# Pipelit

**基于 Claude Code Skill 的 AI 研发流程自动化插件 MVP。**

围绕 release、changelog、飞书任务开发辅助三个高频场景，探索 AI 在研发流程中的落地方式。

> 不替代完整研发流程，不追求端到端自动化。  
> 重点消除研发流程中的摩擦点，用 AI 处理低风险、高重复、规则明确的任务。

## 安装

```bash
/plugin marketplace add hs-ai-projects/pipelit
/plugin install pipelit
```

**前置条件：** Python 3.10+（用于飞书 API，stdlib only，零依赖）

## Skills

| Skill | 触发方式 | 场景 |
|-------|---------|------|
| `using-pipelit` | 不确定用哪个时自动激活 | 路由指南 + L1/L2/L3 任务分级 |
| `feishu-dev` | 飞书任务 ID / URL、`/feishu-dev` | 飞书任务全链路：查询 / L2 开发 / L3 分析 |
| `feishu-commit` | `/feishu-commit <task_id>` | commit 并自动注入飞书任务链接 |
| `release` | "发版"、"打 tag"、"release" | 版本发布（precheck + dry-run + 一次确认） |
| `changelog` | "changelog"、"更新日志" | 生成版本更新文档（Markdown / 飞书 HTML） |
| `guance` | `/guance` | 观测云 ads-backend 错误日志分析（按状态码/接口/错误信息三维聚合） |

## 任务分级

| 级别 | 特征 | AI 动作 |
|------|------|---------|
| L1 | 生成文本、更新配置、写 changelog | 直接执行 |
| L2 | 改代码，≤ 3 文件，范围清晰 | Plan → 用户确认 → 执行 |
| L3 | 复杂改动，影响范围大 | 只分析，不改代码 |

## 配置文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `config.json` | `~/.claude/plugins/cache/pipelit/` | 飞书凭据（自动生成） |
| `release-config.json` | 项目 `.claude/` 目录 | 发版配置（首次发版时引导生成） |
| `release-manifest.json` | `changelog.outputDir` 目录 | 每次 release 后自动写入，供 changelog 读取 |

## .gitignore

以下文件**必须**加入 `.gitignore`，不要提交到 Git：

```gitignore
# Pipelit 配置（含本地路径）
.claude/release-config.json

# changelog 和 manifest 输出（可选，看团队需要）
changelog-workspace/
```

`~/.claude/plugins/cache/pipelit/config.json` 含飞书 App Secret，存放在用户主目录下，不在项目仓库中。

## release 工作流

```
precheck → dry-run 预览 → 一次确认 → 自动执行
              ↓
    fetch 远端 + 检查分支 + 检查工作区
    检查本地/远端同步 + 检查远端 tag
    运行 precheck 命令（lint/build/test）
              ↓
    更新版本文件 → commit → tag → push
              ↓
    写入 release-manifest.json
              ↓
    生成 changelog（读取 manifest range）
```

## PBC 口径

> 围绕研发流程中的任务获取、问题理解、变更执行、版本发布和文档沉淀，完成了 Pipelit 的 MVP 搭建。项目基于 Claude Code Skill，优先落地飞书任务辅助开发、版本发布自动化、changelog 自动生成三个场景，并通过 L1/L2/L3 任务分级、dry-run 预览、人工确认和发布前检查机制，控制 AI 自动化风险。当前版本可支撑 demo 和小范围试用，后续将继续把 release 的关键动作沉淀为稳定流程，并补齐 partial_release、远端检查和回滚能力。
