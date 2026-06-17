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

## Skills

| Skill | 触发方式 | 场景 |
|-------|---------|------|
| `using-pipelit` | 不确定用哪个时自动激活 | 路由指南 + 首次权限检测 + L1/L2/L3 分级说明 |
| `feishu-dev` | 飞书任务 ID / URL、`/feishu-dev` | 飞书任务全链路：查询 / L2 开发 / L3 分析 |
| `release` | "发版"、"打 tag"、"release"、"准备上线" | 版本发布全流程 + 发版后推送飞书卡片 |
| `changelog` | "changelog"、"更新日志"、"发版说明" | 生成版本更新文档（Markdown / 飞书粘贴 HTML） |
| `guance-log-analysis` | "观测云"、"查日志"、"查报错"、`/guance-log-analysis` | 观测云错误日志三维聚合分析 |
| `config` | `/pipelit:config`、"查看配置"、"配置总览" | 配置一览 + 常用字段修改 |

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
    发送飞书卡片到群（左文右图布局，@ 关注人）
```

## 配置文件

配置分**三层**，优先级 L3 > L2 > L1（高层覆盖低层，浅合并）：

| 层 | 位置 | 内容 |
|----|------|------|
| L1 用户级 | `~/.claude/pipelit/config.json` | `user_id`（跨项目全局） |
| L2 项目级 | `<cwd>/.pipelit/config.json` | 飞书凭据、项目路径、发版配置、bot |
| L3 仓库级 | `<repo>/.pipelit.json`（可选） | precheck 命令、特殊规则 |

完整说明见 [docs/config-hierarchy.md](docs/config-hierarchy.md)。

首次使用任意 skill 时会自动引导填写，无需手动创建。也可通过 `/pipelit:config` 查看和修改所有配置。

### 前后端分离项目

在前端目录配置后，插件会自动在后端目录创建 extends 指针：

```
ads-web/.pipelit/config.json   ← 完整配置（canonical）
ads/.pipelit/config.json       ← {"extends": "/abs/path/ads-web/.pipelit/config.json"}
```

两个目录都可以直接使用所有 skill，读写自动路由到 canonical 文件。

### 配置字段说明

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
        "remote": "origin",
        "versionFile": "package.json",
        "versionUpdater": "npm",
        "precheck": []
      }
    ],
    "changelog": { "enabled": true, "outputDir": "changelog-workspace", "audience": "business" },
    "feishuWikiUrl": "https://...",
    "chatId": "oc_xxx"
  },
  "logProvider": "guance",
  "cardFeatures": {
    "linkTask": true,
    "atFollower": true,
    "image": true
  }
}
```

L1 单独存放：
```json
{
  "user_id": "你的飞书 user_id（ou_xxx）"
}
```

观测云配置独立存放于 `<cwd>/.pipelit/guance_config.json`：
```json
{
  "api_key": "观测云 API Key",
  "workspace_id": "wksp_xxx",
  "base_url": "https://cn6-openapi.guance.com"
}
```

| 字段 | 用途 | 写入时机 |
|------|------|---------|
| `app_id` / `app_secret` | 飞书应用凭据 | 首次使用飞书 skill 时引导 |
| `user_id` | 你的飞书用户 ID | 首次配置时引导 |
| `frontend_path` / `backend_path` | 项目路径 | 首次 feishu-dev 时引导 |
| `release` | 发版配置（仓库、changelog、版本策略） | 首次 release 时引导 |
| `logProvider` | 日志源：`guance` / `noop` | 默认 `guance` |
| `cardFeatures` | 发版卡片功能开关 | 默认全开 |

## 系统通知 hook（可选）

AI 等待你输入时，弹出系统托盘通知，避免不知道 AI 在等你：

```bash
# 运行 using-pipelit 时按提示一键配置
/using-pipelit
```

或手动把 [docs/settings-template.json](docs/settings-template.json) 的 `hooks` 段复制到项目 `.claude/settings.json`。

- Windows：`scripts/notify.ps1`（系统托盘气泡）
- Mac/Linux：`scripts/notify.sh`（`osascript` / `notify-send`）

## 决策审计日志

feishu-dev 每次 L2/L3 分级决策都会写入 `~/.claude/pipelit/decision-logs/`，用 `audit.py` 查询：

```bash
# 最近 10 次判定
python3 scripts/audit.py recent

# 某次为什么判 L2/L3
python3 scripts/audit.py why <task_id 前缀>

# 对比两次决策是否一致
python3 scripts/audit.py diff <task_id_1> <task_id_2>
```

## 回归测试

修改 `scripts/` 后必须跑通再提交：

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py
```

## 环境变量

| 变量 | 用途 | 默认值 |
|------|------|-------|
| `CLAUDE_BIN` | claude 命令路径 | 自动探测 |
| `GITLAB_TOKEN` / `GITHUB_TOKEN` | 自动创建 MR/PR 时使用 | — |

---

## TODO：Bot 自动化（待完善）

Bot 监听飞书任务事件，任务指派给你时自动分析并发送卡片到群聊。目前代码已有基础实现，但尚未完整集成到当前配置体系，暂不作为正式功能提供。

<details>
<summary>Bot 架构与部署（参考）</summary>

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
python3 scripts/feishu_bot_longpoll.py serve
```

**Webhook**：需要公网 URL，在飞书后台填写回调地址。

```bash
python3 scripts/feishu_bot_webhook.py serve
# 默认监听 :8765
```

### 额外依赖

```bash
uv pip install lark-oapi   # 飞书 SDK（长连接必须）
uv pip install anthropic   # Claude API
```

### 环境变量

| 变量 | 用途 |
|------|------|
| `ANTHROPIC_API_KEY` | Bot 调用 Claude 分析任务，**必须设置** |
| `BOT_ANALYSIS_MODEL` | 分析任务用的模型 | 
| `BOT_EXECUTION_MODEL` | 执行代码修改用的模型 |

### 飞书后台必配

需订阅的事件：

| 事件名 | 触发时机 |
|--------|---------|
| `task.task.update_user_access_v2` | 任务指派给你（核心） |
| `task.task.created_v1` | 任务创建 |
| `task.v2.task_updated_v1` | 任务更新（Bot 自建任务） |

</details>
