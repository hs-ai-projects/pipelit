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

**前置条件：** Python 3.10+

**Bot 自动化额外依赖（按需安装）：**

```bash
# 飞书 SDK（长连接模式必须）
uv pip install lark-oapi

# Claude API（analyze 分析调用）
uv pip install anthropic
```

## Skills

| Skill | 触发方式 | 场景 |
|-------|---------|------|
| `using-pipelit` | 不确定用哪个时自动激活 | 路由指南 + 首次权限检测 + L1/L2/L3 分级说明 |
| `feishu-dev` | 飞书任务 ID / URL、`/feishu-dev` | 飞书任务全链路：查询 / L2 开发 / L3 分析 |
| `feishu-bot` | "配置飞书机器人"、`/feishu-bot`、"webhook 怎么配" | 服务器部署 + 飞书应用配置 + 排障手册 |
| `release` | "发版"、"打 tag"、"release"、"准备上线" | 版本发布全流程 + 发版后推送飞书卡片 |
| `changelog` | "changelog"、"更新日志"、"发版说明" | 生成版本更新文档（Markdown / 飞书粘贴 HTML） |
| `guance-log-analysis` | "观测云"、"查日志"、"查报错"、`/guance-log-analysis` | 观测云错误日志三维聚合分析 |

## 任务分级

| 级别 | 特征 | AI 动作 |
|------|------|---------|
| L1 | 生成文本、更新配置、写 changelog | 直接执行 |
| L2 | 改代码，≤ 3 文件，范围清晰 | Plan → 用户确认 → 执行 → push |
| L3 | 复杂改动，影响范围大，涉及文件 > 5 | 只输出分析报告，不改代码 |

## Bot 自动化

Bot 监听飞书任务事件，任务指派给你时自动分析并发送卡片到群聊。

### 架构

```
飞书平台
  │  任务创建 / 指派事件
  ▼
Bot 接收层（二选一）
  ├── feishu_bot_longpoll.py   ← 长连接（推荐，无需公网入口）
  └── feishu_bot_webhook.py    ← Webhook（需要公网 URL）
  ▼
feishu_bot_analyzer.py         ← Claude 分析 + 卡片构建 + 执行
  │
  ├── L3 → 分析报告卡片（不改代码）
  ├── L2 feature → 确认卡片 → 用户点按钮 → 无交互实现 → MR → 结果卡片
  └── L2 bug → 全自动修复 → push → MR → 结果卡片
```

### 部署方式

**长连接（推荐）**：不需要公网地址，服务器主动连飞书 WebSocket。

```bash
# 启动
python3 scripts/feishu_bot_longpoll.py serve

# 后台运行（nohup）
nohup python3 scripts/feishu_bot_longpoll.py serve > /tmp/pipelit-bot.log 2>&1 &
```

**Webhook**：需要公网 URL，在飞书后台填写回调地址。

```bash
python3 scripts/feishu_bot_webhook.py serve
# 默认监听 :8765
```

### 飞书后台必配

1. **长连接**：应用 → 事件与回调 → 订阅以下事件（无需填 URL）
2. **Webhook**：应用 → 事件与回调 → 填写事件订阅 URL

需订阅的事件：

| 事件名 | 触发时机 |
|--------|---------|
| `task.task.update_user_access_v2` | 任务指派给你（核心） |
| `task.task.created_v1` | 任务创建 |
| `task.v2.task_updated_v1` | 任务更新（Bot 自建任务） |

### 配置 Bot

```bash
# 初始化 Bot 配置（交互式引导）
python3 scripts/feishu_bot_webhook.py setup
```

Bot 相关配置存入 `config.json` 的 `bot` 字段，详见[配置文件](#配置文件)。

### 调试 CLI

```bash
# 单独测试分析（不发卡片）
python3 scripts/feishu_bot_analyzer.py analyze  <task_id>

# 完整流程（分析 + 发卡片）
python3 scripts/feishu_bot_analyzer.py pipeline <task_id>

# 读取 pending 文件直接执行（需求确认后手动触发）
python3 scripts/feishu_bot_analyzer.py execute  <task_id>

# 查看任务详情
python3 scripts/feishu_api.py get_task_full <task_id>
```

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
    发送飞书卡片到群（左文右图布局，@ 关注人）
```

## 配置文件

配置存储在**用户主目录**，跨工作目录共享：

```
~/.claude/pipelit/config.json
# Windows: %USERPROFILE%\.claude\pipelit\config.json
```

首次使用任意 skill 时会自动引导填写，无需手动创建。

> 旧版本（≤ 0.2.0）的 `.cache/config.json` 会在首次运行时自动迁移到新位置，原文件保留不动。

```json
{
  "app_id": "飞书 App ID",
  "app_secret": "飞书 App Secret",
  "user_id": "你的飞书 user_id（ou_xxx）",
  "frontend_path": "前端项目绝对路径",
  "backend_path": "后端项目绝对路径",
  "bot": {
    "notify_chat_id": "oc_xxx（卡片通知发到哪个群）",
    "user_id": "你的飞书 user_id（任务过滤用）",
    "project_path": "需要改代码的项目路径",
    "trigger_mode": "notify",
    "trigger_events": ["task_assigned", "task_created"]
  },
  "release": {
    "projectName": "my-project",
    "versionStrategy": "unified",
    "repos": [
      {
        "label": "frontend",
        "path": ".",
        "releaseBranch": "master",
        "remote": "origin",
        "versionFile": "package.json",
        "versionUpdater": "npm",
        "precheck": []
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
| `user_id` | 你的飞书用户 ID，运行 `feishu_api.py save_user` 获取 | 首次配置 Bot 时引导 |
| `frontend_path` / `backend_path` | 项目路径 | 首次 feishu-dev 时引导 |
| `bot.notify_chat_id` | 卡片通知发送目标群 ID | Bot setup 时引导 |
| `bot.project_path` | Bot 自动改代码的项目目录 | Bot setup 时引导 |
| `bot.trigger_mode` | `notify`（只发通知）/ `spawn`（自动执行） | Bot setup 时引导 |
| `bot.trigger_events` | 监听哪些事件，支持 `task_assigned` / `task_created` | Bot setup 时引导 |
| `release` | 发版配置（仓库、changelog、版本策略） | 首次 release 时引导 |
| `release.feishuWikiUrl` | changelog 末尾附加的 Wiki 链接 | release 完成后询问 |
| `release.chatId` | 发版后推送卡片的飞书群 ID | release 完成后询问 |

配置文件存在用户主目录，**不会进入任何项目仓库**（自然隔离）。

## 环境变量

| 变量 | 用途 | 默认值 |
|------|------|-------|
| `ANTHROPIC_API_KEY` | Bot 调用 Claude 分析任务，**必须设置** | — |
| `CLAUDE_BIN` | claude 命令路径 | 自动探测 |
| `BOT_ANALYSIS_MODEL` | 分析任务用的模型（快速分类） | `claude-haiku-4-5-20251001` |
| `BOT_EXECUTION_MODEL` | 执行代码修改用的模型 | `claude-sonnet-4-6` |
| `GITLAB_TOKEN` / `GITHUB_TOKEN` | 自动创建 MR/PR 时使用 | — |
