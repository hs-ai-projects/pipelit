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

### Step 2：判断是否缺少必要配置

**A. Bash 权限**：检查以下两条关键规则是否存在（有其中任意一条即视为已配置）：
- `"Bash(git status*)"` 或 `"Bash(git *)"` 或 `"Bash(git -C *)"`
- `"Bash(PYTHONIOENCODING=utf-8 python3*)"` 或 `"Bash(python3*)"`

**B. AskUserQuestion hook**（可选但推荐）：检查 `hooks.PreToolUse` 中是否存在 `matcher: "AskUserQuestion"` 的 hook。

判断逻辑：
- A 和 B 都已配置 → 跳过，直接展示路由指南
- A 未配置 → 执行 Step 3（引导添加权限，同时问是否要加 hook）
- A 已配置但 B 未配置 → 执行 Step 4（仅询问是否添加 hook）

### Step 3：提示用户添加权限（+ 可选 hook）

用 AskUserQuestion 询问：

```
⚙️ Pipelit 首次使用检测

当前项目的 .claude/settings.json 缺少必要的 Bash 命令权限。
没有这些权限，skill 运行时会频繁弹出确认提示。

是否自动添加到当前项目？
  ● 是，添加权限 + 通知 hook（推荐）
  ○ 是，仅添加权限
  ○ 否，我手动处理
```

用户选**添加权限 + 通知 hook** 或**仅添加权限**时，执行以下命令合并规则：

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

若用户选了**添加权限 + 通知 hook**，额外执行 Step 4 的 hook 写入逻辑。

成功后提示：

```
✅ 权限已添加到 .claude/settings.json
后续 skill 运行不再重复弹出确认。
```

用户选**否**时：跳过，直接展示路由指南。

### Step 4：引导添加 AskUserQuestion 系统通知 hook（可选）

若 A 已配置但 B 未配置，或用户选了"添加权限 + 通知 hook"，用 AskUserQuestion 询问：

```
🔔 Pipelit 通知 hook（可选）

AI 调用 AskUserQuestion 等待你输入时，可以弹出系统通知，
避免你不知道 AI 在等你而"卡住"。

是否添加？
  ● 是，添加通知 hook（Windows 气泡通知）
  ○ 否，不需要
```

用户选**是**时，执行：

```bash
node -e "
const fs = require('fs');
const os = require('os');
const file = '.claude/settings.json';
const isWin = os.platform() === 'win32';
const cmd = isWin
  ? 'powershell.exe -NonInteractive -ExecutionPolicy Bypass -File \"scripts/notify.ps1\" 2>/dev/null; exit 0'
  : 'bash scripts/notify.sh 2>/dev/null; exit 0';
const existing = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
existing.hooks = existing.hooks || {};
existing.hooks.PreToolUse = existing.hooks.PreToolUse || [];
const alreadyHasHook = existing.hooks.PreToolUse.some(h => h.matcher === 'AskUserQuestion');
if (!alreadyHasHook) {
  existing.hooks.PreToolUse.push({
    matcher: 'AskUserQuestion',
    hooks: [{ type: 'command', command: cmd }]
  });
}
fs.writeFileSync(file, JSON.stringify(existing, null, 2));
console.log('done');
"
```

成功后提示：

```
✅ 通知 hook 已添加
以后 AI 等待你输入时会弹出系统通知（Windows 托盘气泡 / macOS 通知中心 / Linux notify-send）。
通知脚本位于 scripts/notify.ps1 和 scripts/notify.sh，可自行修改提示内容。
```

---

## Skill 速查

| Skill | 触发词 | 适用场景 |
|-------|--------|---------|
| `feishu-dev` | 飞书任务 ID / URL、"帮我完成飞书任务"、"列出飞书任务"、`/feishu-dev` | 飞书任务全链路：查询、L2 开发、L3 分析 |
| `feishu-bot` | "配置飞书机器人"、"webhook 怎么配"、"机器人收不到事件"、"feishu-bot setup" | Webhook 服务器安装、飞书应用配置、GitLab Token、排障手册 |
| `release` | "发版"、"打 tag"、"release"、"准备上线" | 版本发布全流程 |
| `changelog` | "changelog"、"更新日志"、"发版说明" | 生成版本更新文档 |
| `guance-log-analysis` | "观测云"、"查日志"、"查报错"、"接口报错"、"分析错误"、"guance logs" | 直接分析观测云日志（单独使用时）；feishu-dev 内部已通过 log-provider 自动调用 |

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

## 决策树（用户输入 → Skill 路由）

```
用户说了什么？
│
├─ 飞书任务 ID / URL / "帮我做飞书任务" / "列出任务"
│   └─→ feishu-dev
│         ├─ 任务量少、描述清晰、改动 ≤ 3 文件 → 自动判 L2（改代码）
│         └─ 描述模糊 / 跨模块 / 文件 > 5       → 自动判 L3（仅分析）
│
├─ "发版" / "打 tag" / "release" / "准备上线" / "继续发版"
│   └─→ release
│
├─ "changelog" / "更新日志" / "发版说明"
│   └─→ changelog
│
├─ "配置飞书机器人" / "webhook 怎么配" / "机器人收不到事件"
│   └─→ feishu-bot
│
├─ "观测云" / "查日志" / "查报错"（单独使用，非 feishu-dev 内部）
│   └─→ guance-log-analysis
│
└─ 不确定 / 混合场景
    └─→ 展示本路由指南，让用户选择
```

---

## Skill 间数据流

```
feishu-dev ──────────────────────────────────────────────────────────────┐
  │                                                                        │
  │ Phase 1.1: get_task_full()                                            │
  │   → 任务详情 + 附件图片 + 视频路径                                       │
  │                                                                        │
  │ Phase 1.8d: log_providers/dispatch.py                                  │
  │   → 读 config.logProvider → guance.py / noop.py                       │
  │   ← log_summary（null = 静默跳过）                                      │
  │                                                                        │
  │ Phase 2: Plan（含 log_summary）→ 用户确认                               │
  │                                                                        │
  │ Phase 3.6: commit（Feishu-Task: <url> 写入 commit body）               │
  │                  ↓                                                     │
  │           release 的 Phase 1.3 git log 读取这个 body                   │
  │           → changelog entry 自动关联飞书任务链接                         │
  │                                                                        │
  └─→ release ──────────────────────────────────────────────────────────→ changelog
        │                                                                  │
        │ Phase 3.6: 读 git log --format="%B"                             │
        │   → 提取 Feishu-Task: URL                                       │
        │   → 关联任务 → @ 关注人 → 发版卡片                               │
        │                                                                  │
        │ Phase 卡片: card_builder.py                                      │
        │   → 读 config.cardFeatures                                       │
        │   → 决定是否附任务链接 / @ / 图片                                  │
        │                                                                  │
        └─→ 发版卡片 → 飞书群                                               │
                                                                          │
        changelog 读 release-manifest.json                                │
          → 生成 CHANGELOG.md / release notes                             │
```

**跨 skill 的关键数据契约**：

| 数据 | 生产方 | 消费方 | 存储位置 |
|------|--------|--------|---------|
| `Feishu-Task: <url>` | feishu-dev Phase 3.6 commit | release Phase 1.3 | git commit body |
| `release-manifest.json` | release Phase 3.5 | changelog | `<repo>/changelog-workspace/` |
| `.feishu-dev-state.json` | feishu-dev 各 Phase | feishu-dev RESUME-CHECK | 工作目录根 |
| `.release-state.json` | release Phase 3.1 | release resume | 工作目录根 |
| `decision-logs/` | feishu-dev Phase 1.3 | 审计/diff | `~/.claude/pipelit/decision-logs/` |

---

## 快速判断

```
飞书任务 ID / URL                        → feishu-dev（自动判断 L2 或 L3）
改动文件 ≤ 3，需求清晰                   → feishu-dev 走 L2 完整开发流程
改动文件 > 5，或逻辑复杂                 → feishu-dev 走 L3 只输出分析报告
只生成文本 / 更新配置 / 写 changelog     → release（L1）
```

## 配置文件

> 详细三层说明见 `docs/config-hierarchy.md`。

配置分三层，优先级 L3 > L2 > L1：

| 层 | 位置 | 内容 |
|----|------|------|
| L1 用户级 | `~/.claude/pipelit/config.json` | 飞书凭据、观测云凭据、logProvider、cardFeatures |
| L2 项目级 | `<cwd>/.pipelit/config.json` | 项目路径、发版配置 |
| L3 仓库级 | `<repo>/.pipelit.json`（可选） | precheck 命令、特殊规则 |

```json
// L1 示例
{
  "app_id": "cli_xxxx",
  "app_secret": "xxxx",
  "logProvider": "guance",
  "cardFeatures": { "linkTask": true, "atFollower": true, "image": true }
}
```

| 字段 | 用途 | 写入时机 |
|------|------|---------|
| `app_id` / `app_secret` | 飞书凭据 | 首次使用飞书 skill 时引导 |
| `frontend_path` / `backend_path` | 项目路径（L2） | 首次 feishu-dev 时引导 |
| `release` | 发版配置（L2） | 首次 release 时引导 |
| `logProvider` | 日志源：guance / noop | 可选，默认 guance |
| `cardFeatures` | 卡片功能开关 | 可选，默认全 true |
