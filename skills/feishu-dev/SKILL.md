---
name: feishu-dev
description: >
  飞书任务全链路处理。触发方式：飞书任务 ID / URL、"帮我完成飞书任务"、"列出飞书任务"、
  /feishu-dev <task_id>、"飞书开发"。
  自动判断任务复杂度：L2（改代码）走完整开发流程，L3（复杂高风险）只做分析不执行。
---

# 飞书任务处理

处理所有飞书任务相关请求：查任务、列任务、开发实现、分析复杂问题。

**L2 任务**：拉取需求 → 补问 → Plan → 实现 → 验证 → commit → **确认后 push**，人工介入 3 个点。
**L3 任务**：拉取需求 → 分析定位 → 输出报告，不改代码，不 commit。

脚本：`${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py`

---

## 快捷入口：列出飞书任务

用户说"列出飞书任务"、"我的飞书待办"时，**跳过所有 Phase，直接执行**：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" list_tasks
# 已完成：list_tasks --completed
```

展示任务列表后结束，不进入开发流程。

---

## Phase 0：项目路径配置（一次性）

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" check_project_config
```

若未配置，询问用户：
```
【项目路径未配置】请提供项目路径（没有的填 null）：
- 前端路径（如 /Users/xxx/work/my-web）
- 后端路径（如 /Users/xxx/work/my-api）
```

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" save_project_config "<frontend>" "<backend>"
```

---

## Phase 1：拉取 + 理解需求

### 1.1 检查凭据

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" check_config
```

未配置则引导用户完成飞书应用凭据配置（参考 feishu-task 凭据配置步骤）。

### 1.2 拉取任务

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" get_task <task_id>
```

记录 `task_id`、`task_summary`、任务链接备用。

### 1.3 复杂度判断（L2 继续 / L3 转分析）

读完任务后，先判断是否属于 L3 高风险，**满足任意一条即为 L3**：

- 描述涉及架构调整、多模块重构、整体改版
- 预计影响文件 > 5 个，或需要跨多个模块
- 线上事故、根因不明、影响范围不确定
- 描述极其模糊，补问也无法收敛到具体文件

**若为 L3**：输出分析报告后结束，不创建分支、不改代码、不 commit：

```
━━━ L3 分析报告 ━━━
任务: <标题>
链接: <飞书任务链接>

问题定位:
  <根据任务描述和代码库推断的可能原因>

涉及范围:
  <可能相关的模块/文件>

建议拆分:
  1. <子任务1>
  2. <子任务2>
  ...

⚠️ 此任务复杂度较高，建议人工拆分后逐个处理。
━━━━━━━━━━━━━━━━━
```

**若为 L2**：继续执行后续 Phase。

### 1.4 检测子任务

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" get_subtasks <task_id>
```

若有子任务，按顺序串行执行每个子任务的完整流程（Phase 1.5 → Phase 4），每个完成后询问是否继续。

### 1.5 加载项目规范

根据任务范围，从 Phase 0 的路径读取对应 CLAUDE.md（存在才读，不存在跳过）。

### 1.6 清晰度检查

读完任务后自我评估，**同时满足以下条件才继续**，否则先补问：
- 知道要改哪个模块/页面（或能通过 1-2 次 grep 确定）
- 知道改什么（增/删/改，有具体描述）
- Bug 类任务：有截图、报错信息或日志中至少一项

**补问**（满足任意一条时用 AskUserQuestion）：
- 不知道涉及哪个页面或模块
- 描述过于模糊（"优化一下"、"看看这个问题"）
- Bug 类但没有任何复现证据

补问一次说完所有疑问，不分多轮。

### 1.7 定位目标文件

用任务关键词 grep 代码库，找到候选文件后读取前 30 行确认功能。
若命中多个候选，用 AskUserQuestion 让用户选择。

---

## Phase 2：Plan（用户确认）

```
━━━ 实现计划 ━━━
任务: <标题>
链接: <飞书任务链接>
页面: <目标文件路径>
范围: 仅前端 / 仅后端 / 前后端

要改:
  ✂ <改动点1>
  ✂ <改动点2>

不动:
  ✗ <相邻不改的功能>

确认后自动执行 →
━━━━━━━━━━━━━━━
```

等用户确认或修正后再进入 Phase 3。

---

## Phase 3：执行

### 3.1 创建分支

```
当前在 master/main/dev → 创建 feat/feishu-{task_id 前 8 位}
当前在 feature 分支    → 直接在当前分支开发
分支已存在            → 切换到已有分支
```

### 3.2 实现代码

按 Plan 逐项修改，遵循已加载的 CLAUDE.md 规范，先找项目中相似写法再仿写，只改计划中列出的内容。

### 3.3 验证

先检测可用的验证命令，再执行：

```bash
# 前端：读 package.json scripts，优先选 type-check > build > lint
node -e "const s=require('./package.json').scripts||{}; console.log(['type-check','build','lint'].find(k=>s[k])||'none')"
```

```bash
# 后端：语法检查
python3 -m py_compile <changed_files>
```

验证失败自动修复，最多重试 3 轮，3 轮后仍失败则暂停报告。

### 3.4 代码 Review

实现完成后自检：
- **范围**：只改了 Plan 里的文件，无计划外改动，无 console.log / debugger / TODO 残留
- **质量**：有无更简洁的写法，有无边界值/空值/异步竞态问题

发现问题直接修掉，改动较大时在收尾报告里说明。

### 3.5 Commit

开始前记录 `git status` 快照，只 add 新增/修改的文件，绝不使用 `git add -A` 或 `git add .`。

```
<type>: <根据实际 diff 写的描述>

Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=<task_id>
Co-Authored-By: Claude <noreply@anthropic.com>
```

Type 判断：含"新增/添加" → `feat`，含"修复/bug" → `fix`，含"删除/重构" → `refactor`，含"优化" → `perf`，兜底 → `feat`。

### 3.6 Push 确认

commit 完成后，**暂停并询问用户**：

```
代码已提交：<commit hash> <commit message 首行>
分支：<branch>

是否推送到远程？
  ● 是，推送
  ○ 否，稍后手动推送
```

用户确认后执行：
```bash
git push origin <branch>
```

绝不推送到 master/main/dev。

---

## Phase 4：收尾

### 4.1 询问是否标记任务完成

Push 成功后询问用户：

```
代码已推送。是否将飞书任务标记为完成？
  ● 是
  ○ 否（等 PR 合并后再关）
```

用户选是时执行：
```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" complete_task <task_id>
```

### 4.2 输出报告

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ 开发完成
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
任务: <标题>
链接: <飞书任务链接>

做了什么: <一句话概述>
改了: <文件路径> (+N -M)
验证: <命令> ✅
Commit: <hash> <message 首行>
Branch: <分支名>
Pushed: ✅ / 待推送
飞书已完成: ✅ / 待确认
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 异常处理

| 异常 | 处理 |
|------|------|
| 凭据未配置 | 引导配置 |
| 任务拉取失败 | 重试 1 次，仍失败报错 |
| 描述有歧义 | AskUser 补问 |
| grep 找不到目标 | 扩大搜索范围，确实找不到则问人 |
| 验证失败 | 自动修复，最多 3 轮，3 轮后暂停 |
| push 失败 | 报错并输出手动推送命令 |
