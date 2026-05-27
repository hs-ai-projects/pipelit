---
name: using-pipelit
description: Pipelit 路由指南。不确定用哪个 skill 时自动激活。包含各 skill 触发场景和 L1/L2/L3 任务分级规则。
---

# Pipelit — 使用指南

Pipelit 是 AI 研发流程自动化插件集，覆盖飞书任务、版本发布、代码提交等高频研发场景。

---

## 首次使用：权限检测

**每次 using-pipelit 被激活时，先执行此检测，再展示路由指南。**

### Step 1：读取当前项目的 settings.json

```bash
cat .claude/settings.json 2>/dev/null || echo "NOT_FOUND"
```

### Step 2：判断是否缺少必要的 Bash 权限

检查以下两条关键规则是否存在（有其中任意一条即视为已配置）：
- `"Bash(git status*)"` 或 `"Bash(git *)"` 或 `"Bash(git -C *)"`
- `"Bash(PYTHONIOENCODING=utf-8 python3*)"` 或 `"Bash(python3*)"`

**若已存在 → 跳过，直接展示路由指南。**

**若不存在 → 执行 Step 3。**

### Step 3：提示用户添加权限

用 AskUserQuestion 询问：

```
⚙️ Pipelit 首次使用检测

当前项目的 .claude/settings.json 缺少必要的 Bash 命令权限。
没有这些权限，skill 运行时会频繁弹出确认提示。

是否自动添加到当前项目？
  ● 是，立即添加（推荐）
  ○ 否，我手动处理
```

用户选**是**时，执行以下命令合并规则：

```bash
node -e "
const fs = require('fs');
const path = require('path');
const dir = '.claude';
const file = path.join(dir, 'settings.json');
const newRules = [
  'Bash(git status*)', 'Bash(git diff*)', 'Bash(git log*)',
  'Bash(git add *)', 'Bash(git commit*)', 'Bash(git push*)',
  'Bash(git fetch*)', 'Bash(git tag*)', 'Bash(git branch*)',
  'Bash(git checkout*)', 'Bash(git ls-remote*)', 'Bash(git rev-list*)',
  'Bash(git show*)', 'Bash(git -C *)',
  'Bash(PYTHONIOENCODING=utf-8 python3*)',
  'Bash(python3 -m py_compile*)', 'Bash(python3*)',
  'Bash(node -e*)', 'Bash(npm *)',
  'Bash(cat .claude/*)', 'Bash(ls *)', 'Bash(mkdir *)'
];
if (!fs.existsSync(dir)) fs.mkdirSync(dir);
const existing = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
existing.permissions = existing.permissions || {};
const current = existing.permissions.allow || [];
existing.permissions.allow = [...new Set([...current, ...newRules])];
fs.writeFileSync(file, JSON.stringify(existing, null, 2));
console.log('done');
"
```

成功后提示：

```
✅ 权限已添加到 .claude/settings.json
后续 skill 运行不再重复弹出确认。
```

用户选**否**时：跳过，直接展示路由指南。

---

## Skill 速查

| Skill | 触发词 | 适用场景 |
|-------|--------|---------|
| `feishu-dev` | 飞书任务 ID / URL、"帮我完成飞书任务"、"列出飞书任务"、`/feishu-dev` | 飞书任务全链路：查询、L2 开发、L3 分析 |
| `feishu-bot` | "配置飞书机器人"、"webhook 怎么配"、"机器人收不到事件"、"feishu-bot setup" | Webhook 服务器安装、飞书应用配置、GitLab Token、排障手册 |
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

**路径：** `/release`，一键执行，不需要 Plan

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
只生成文本/更新配置/写 changelog  → release（L1）
```

## 配置文件

所有配置统一存储在 `~/.claude/pipelit/config.json`（跨工作目录共享），一次配置全局生效：

```json
{
  "app_id": "飞书 App ID",
  "app_secret": "飞书 App Secret",
  "frontend_path": "前端项目路径",
  "backend_path": "后端项目路径",
  "release": { "repos": [...], "changelog": {...}, ... }
}
```

| 字段 | 用途 | 写入时机 |
|------|------|---------|
| `app_id` / `app_secret` | 飞书凭据 | 首次使用飞书 skill 时引导 |
| `frontend_path` / `backend_path` | 项目路径 | 首次 feishu-dev 时引导 |
| `release` | 发版配置 | 首次 release 时引导 |
