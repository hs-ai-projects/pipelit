# Pipelit

**基于 Claude Code Skill 的 AI 研发流程自动化插件。**

围绕飞书任务开发、版本发布、changelog 生成、日志分析四个高频场景，用 AI 消除研发流程中的摩擦点。

> 不替代完整研发流程，不追求端到端自动化。  
> 重点处理低风险、高重复、规则明确的任务。

## 安装

```bash
/plugin marketplace add hs-ai-projects/pipelit
/plugin install pipelit
```

**前置条件：** Python 3.10+（stdlib only，零外部依赖）

## Skills

| Skill | 触发方式 | 场景 |
|-------|---------|------|
| `using-pipelit` | 不确定用哪个时自动激活 | 路由指南 + 首次权限检测 + L1/L2/L3 分级 |
| `feishu-dev` | 飞书任务 ID / URL、`/feishu-dev` | 飞书任务全链路：查询 / L2 开发 / L3 分析 |
| `release` | "发版"、"打 tag"、"release"、"准备上线" | 版本发布全流程 + 发版后推送飞书卡片 |
| `changelog` | "changelog"、"更新日志"、"发版说明" | 生成版本更新文档（Markdown / 飞书粘贴 HTML） |
| `guance-log-analysis` | "观测云"、"查日志"、"查报错"、`/guance-log-analysis` | 观测云错误日志三维聚合分析 |

## 任务分级

| 级别 | 特征 | AI 动作 |
|------|------|---------|
| L1 | 生成文本、更新配置、写 changelog | 直接执行 |
| L2 | 改代码，≤ 3 文件，范围清晰 | Plan → 用户确认 → 执行 → push |
| L3 | 复杂改动，影响范围大，涉及文件 > 5 | 只输出分析报告，不改代码 |

## release 工作流

```
precheck → dry-run 预览 → 一次确认 → 全自动执行
              ↓
    git fetch + 检查分支/工作区/远端同步
    检查版本文件 + 远端 tag 冲突
    运行自定义 precheck 命令（lint/build/test）
              ↓
    更新版本文件 → commit → tag → push
              ↓
    生成 changelog（Markdown + 飞书 HTML）
    生成版本更新概述
              ↓
    询问是否发送飞书卡片到群（左文右图布局）
```

## 配置文件

配置存储在**用户主目录**，跨工作目录共享，路径为：

```
~/.claude/pipelit/config.json        (Windows: %USERPROFILE%\.claude\pipelit\config.json)
```

首次使用任意 skill 时会自动引导填写，无需手动创建。从任何工作目录调用 skill 都能读到同一份配置。

> 旧版本（≤ 0.2.0）的 `.cache/config.json` 会在首次运行时自动迁移到新位置，原文件保留不动。

```json
{
  "app_id": "飞书 App ID",
  "app_secret": "飞书 App Secret",
  "frontend_path": "前端项目绝对路径",
  "backend_path": "后端项目绝对路径",
  "release": {
    "projectName": "my-project",
    "versionStrategy": "unified",
    "repos": [
      {
        "label": "frontend",
        "path": ".",
        "releaseBranch": "master",
        "versionFile": "package.json"
      }
    ],
    "changelog": { "enabled": true, "outputDir": "changelog-workspace", "audience": "business" },
    "feishuWikiUrl": "https://...",
    "chatId": "oc_xxx"
  }
}
```

| 字段 | 用途 | 写入时机 |
|------|------|---------|
| `app_id` / `app_secret` | 飞书应用凭据 | 首次使用飞书 skill 时引导 |
| `frontend_path` / `backend_path` | 项目路径 | 首次 feishu-dev 时引导 |
| `release` | 发版配置（仓库、changelog、版本策略） | 首次 release 时引导 |
| `release.feishuWikiUrl` | changelog 末尾附加的 Wiki 链接 | release 完成后询问 |
| `release.chatId` | 发版后推送卡片的飞书群 ID | release 完成后询问 |

配置文件存在用户主目录，**不会进入任何项目仓库**（自然隔离）。
