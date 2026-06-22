---
name: feishu-dev
description: >
  飞书任务全链路处理。触发方式：飞书任务 ID / URL、"帮我完成飞书任务"、"帮我做飞书任务"、
  "列出飞书任务"、"列出修复中的任务"、"我的修复中任务"、"开始干活"、/feishu-dev <task_id>、"飞书开发"。
  支持拉取任务列表后直接选择开发。
  自动判断任务复杂度：L2（改代码）走完整开发流程，L3（复杂高风险）只做分析不执行。
---

## 权限检测（首次使用自动执行）

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_permissions.py"
```

若 `bash_ok` 为 false 或 `hook_ok` 为 false，读取并按指引完成配置：

```bash
cat "${CLAUDE_PLUGIN_ROOT}/skills/_shared/permissions-setup.md"
```

配置完成后继续当前任务。

---

# 飞书任务处理

处理所有飞书任务相关请求：查任务、列任务、开发实现、分析复杂问题。

**L2 任务**：拉取需求（一次调用） → 补问 → **【确认 Plan】** → 自动实现+静态验证 → **【用户验证功能】** → 自动 commit+push+标记完成。仅 2 个人工介入点。
**L3 任务**：拉取需求 → 分析定位 → 输出报告，不改代码，不 commit。

## 自动化模式（BOT_AUTO_EXECUTE）

**[MODE-CHECK]** 启动时第二件事：检查 prompt 中是否包含 `BOT_AUTO_EXECUTE`，并**输出一行 log**：

```
[MODE-CHECK] BOT_AUTO_EXECUTE: <yes / no>
```

**若 prompt 中包含 `BOT_AUTO_EXECUTE`，进入全自动模式：**
- Phase 2（Plan 确认）：**跳过等待**，直接输出 Plan 后立即执行 Phase 3
- Phase 3.5（用户验证）：**跳过等待**，自检通过后直接 commit + push + 标记完成
- Phase 1.6（清晰度补问）：**跳过**，直接基于已有信息执行
- 若 prompt 中已包含改动计划（`已完成分析，直接按以下计划执行`），**跳过 Phase 1**，直接使用提供的计划进入 Phase 2

**不在 BOT_AUTO_EXECUTE 模式时（`[MODE-CHECK] BOT_AUTO_EXECUTE: no`）：**
- **Phase 3.5 不可省略**：即使 AI 自检通过，也必须暂停等待用户验证
- **Phase 2 Plan 必须等用户确认**：不能自动跳过
- 各 Phase 跳过用户验证前必须 re-check `[MODE-CHECK]` 标志

---

脚本：`${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py`

---

## 快捷入口

### 列出飞书任务

用户说"列出飞书任务"、"我的飞书待办"、"看看我的任务"时：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" list_tasks
# 已完成：list_tasks --completed
```

用户说"列出修复中的任务"、"我的修复中任务"、"待修复的任务"、"哪些任务在修复"时，加 `--status fixing` 过滤：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" list_tasks --status fixing
```

展示任务列表后，用 AskUserQuestion 询问：

```
你的待办任务：
  1. <任务标题1>  (截止: xx-xx)
  2. <任务标题2>  (截止: xx-xx)
  ...

选择一个任务开始开发，或回复"仅查看"结束。
```

- 用户选了某个任务 → 用该 task_id 直接进入 Phase 1
- 用户回复"仅查看" → 结束

### 帮我做飞书任务

用户说"帮我做飞书任务"、"做一个飞书任务"、"开始干活"时，**自动拉取任务列表并让用户选择**，等同于先 list 再选。

---

## Phase 1：拉取 + 理解需求（一次调用）

### 1.1 拉取任务全量上下文

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" get_task_full <task_id>
```

一次返回：任务详情、子任务、附件图片（已自动下载到本地）、项目配置。

记录 `task.id`、`task.summary`、任务链接备用。

**异常处理**：
- 返回 `{"error": "凭据未配置"}` 或 `project_config.configured` 为 false → 进入**首次配置向导**（见下方）

#### 首次配置向导

首次配置前，**先自动检测项目路径**：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" detect_project_paths
```

若检测到路径（`frontend` 或 `backend` 字段不为 null），通过 AskUserQuestion 展示检测结果并让用户确认：

```
检测到可能的项目路径：
  前端: <frontend.path>（<frontend.type>，置信度：<frontend.confidence>）
  后端: <backend.path>（<backend.type>，置信度：<backend.confidence>）

是否使用以上路径？
  ● 确认（直接使用）
  ○ 手动调整
```

用户选"确认"→ 直接调用 `save_project_config`；选"调整"→ 走原有的手动填写流程。

检测结果为空时，跳过检测步骤，直接走手动填写流程。

**禁止从 memory 自动填充任何路径或凭据。** 必须用 AskUserQuestion 一次性收集所有配置：

```
首次使用需要完成配置，请提供以下信息：

1. 前端项目路径（如 /Users/xxx/ads-web）
2. 后端项目路径（如 /Users/xxx/ads，无后端填"无"）
3. 飞书 App ID（如 cli_xxx）
4. 飞书 App Secret
5. 观测云 API Key（可选，跳过填"跳过"）
6. 观测云 Workspace ID（可选）
```

收到回复后依次调用：

```bash
# 前后端路径
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" \
  save_project_config <frontend_path|null> <backend_path|null>

# 飞书凭据
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" \
  save_config <app_id> <app_secret>

# 观测云（若用户未跳过）
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guance_api.py" \
  save_config <api_key> <workspace_id>
```

配置完成后继续当前任务。

### 1.2 附件图片处理

检查返回的 `has_images`、`images`、`has_videos`、`videos` 字段：

**若 `has_images` 为 true**：用 Read 工具读取已下载的图片文件（`images[].path`），作为任务上下文。

同时使用结构化标注数据辅助分析：

**`image_annotations` 字段**（由 image_annotator 自动产出）：
若 `image_annotations[<path>].annotation_count > 0`，优先读取标注列表：
- `color`：标注颜色（`red` / `green` / `yellow`），红色为最高优先级
- `crop_path`：已裁剪的标注区域图片路径，用 Read 工具读取放大查看
- 标注区域旁边的文字是用户的说明，是定位 bug 的首要线索

若 `image_annotations` 为空（Pillow 未安装或标注颜色太淡）：降级到直接用 Read 读原图，人工识别红色圈/框/箭头。

记录所有标注信息为 `red_annotations`，在后续分析中优先作为定位依据

**若 `has_videos` 为 true**：输出提示（不阻断流程）：

```
[1.2] 发现 <N> 个视频附件，已下载到本地，需人工查看：
  - <videos[0].path>
  - <videos[1].path>
（视频内容未自动分析，请在本地播放器查看后告知关键信息）
```

**若 `has_images` 为 false 且 `has_videos` 为 false 但 `task.description` 包含 `[Image]`**：说明有内联图片但无附件，用 AskUserQuestion 补问：

```
任务描述里有图片，但飞书 API 无法获取内联图片。
请直接把截图粘贴到这里，或用文字描述图片内容。
```

**三者都没有**：直接跳过。

### 1.3 复杂度判断（L2 继续 / L3 转分析）

按 `rules/classification.md` 的决策树执行判定，**按优先级自上而下匹配，命中即返回**。

判定完成后，**输出一行 log**：`[1.3] 分级结果：<L2/L3>，命中规则：<规则名>，候选文件数=<N>，描述长度=<N>，截图=<有/无>`

**若为 L3**：输出分析报告后结束，不创建分支、不改代码、不 commit：

**若未执行过 1.8，先执行 1.8（bug 日志辅助），再输出以下报告。**

```
━━━ L3 分析报告 ━━━
任务: <标题>
链接: <飞书任务链接>

问题定位:
  <根据任务描述和代码库推断的可能原因>

涉及范围:
  <可能相关的模块/文件>

（若 log_summary 不为 null，插入以下节）
━━ 🔍 观测云 Log 佐证 ━━
<log_summary 内容>
结合日志结论: <log 数据对上述定位的印证或修正>
━━━━━━━━━━━━━━━━━━━━━━

建议拆分:
  1. <子任务1>
  2. <子任务2>
  ...

⚠️ 此任务复杂度较高，建议人工拆分后逐个处理。
━━━━━━━━━━━━━━━━━
```

**若为 L2**：继续执行后续 Phase。

### 1.4 子任务处理

若 `has_subtasks` 为 true，按顺序串行执行每个子任务的完整流程（Phase 1.5 → Phase 4），每个完成后询问是否继续。

### 1.5 加载项目规范

根据 `project_config` 的路径读取对应 CLAUDE.md（存在才读，不存在跳过）。

### 1.6 清晰度检查

读完任务（含用户补充的图片/描述）后自我评估，**同时满足以下条件才继续**，否则先补问：
- 知道要改哪个模块/页面（或能通过 1-2 次 grep 确定）
- 知道改什么（增/删/改，有具体描述）
- Bug 类任务：有截图、报错信息或日志中至少一项

**补问**（满足任意一条时用 AskUserQuestion）：
- 不知道涉及哪个页面或模块
- 描述过于模糊（"优化一下"、"看看这个问题"）
- Bug 类但没有任何复现证据

补问一次说完所有疑问，不分多轮。

### 1.7 定位目标文件

**优先级从高到低**：

1. **截图 URL（最高优先级）**：若 1.2 读取的截图中包含 Network 面板、URL 栏、错误信息中的接口路径，**直接提取完整 URL 路径**（含子路径，如 `/api/ads/create-ads/report` 而非 `/api/ads/create-ads`），作为接口定位的权威来源。
2. **任务描述**：从任务描述中提取页面/模块名，grep 定位。
3. **grep 兜底**：用任务关键词 grep 代码库。

定位后（**前后端并行 grep**，减少等待）：
```bash
grep -rn "<路径>" <frontend_path>/src --include="*.ts" --include="*.vue" &
grep -rn "<路径>" <backend_path> --include="*.py" &
wait
```

**有后端路径时（`backend_path` 已配置）：前后端必须同时排查，不可只改前端。** 即使任务描述只提到前端现象，也要确认后端接口是否正常、是否需要同步修改。

- 找到候选文件后读取前 30 行确认功能。
- 候选 > 3 个时，**强制收敛到最长公共前缀**，用 AskUserQuestion 让用户选择。
- AskUserQuestion 候选展示要列出**具体文件路径**而非"接口模块"。

### 1.7b 接口路径精确匹配

从 1.7 定位到的文件 + 截图 URL 中提取接口路径，在代码库中 grep 确认：

```bash
grep -rn "<从截图提取的完整URL路径>" <frontend_path>/src --include="*.ts" --include="*.vue" --include="*.js"
```

**关键**：不能只搜父路径（如 `/api/ads/create-ads`），必须包含子路径（如 `/api/ads/create-ads/report`）。

---

### 1.8 Bug 日志辅助（仅 bug 任务触发）

#### 1.8a 判断是否为 bug 任务

> 判定规则见 `rules/bug-triggers.md`（特征表 + 反特征 + 截图优先原则）。

读完任务（含图片、附件）后，按 `rules/bug-triggers.md` 语义判断任务意图是否为"某个功能出了问题需要排查"。

判断完成后，**必须输出一行 log**：

```
[1.8a] bug任务判断：<是 / 否>，理由：<一句话>
```

**判断为 bug 任务** → 继续 1.8b。**否则跳过整个 1.8**，输出 `[1.8] 跳过（非 bug 任务）`。

#### 1.8b 代码接口预定位

结合 1.7 已定位的目标文件及任务描述，在前端项目目录 grep API 调用，找候选接口路径：

```bash
# 搜索 api 目录下与功能模块相关的接口定义
grep -rn "url\|path\|api" <frontend_path>/src/api --include="*.ts" | grep -i "<功能关键词>"
```

读取命中文件，提取与当前 bug 功能模块语义匹配的接口路径前缀，得到候选列表（可为空数组）。候选列表可为空数组，直接继续执行 1.8c，不补问。

#### 1.8c 时间推断

> 窗口计算规则见 `rules/time-window.md`（优先级表 + ISO 8601 格式要求 + 调参场景）。

按 `rules/time-window.md` 推断时间窗口（P1 截图时间 > P2 描述短语 > P3 created_at）：

记录：
- `bug_start`：推断时间点 - 窗口（ISO 8601 + 时区）
- `bug_end`：推断时间点 + 15 分钟（ISO 8601 + 时区）

#### 1.8d 调用日志查询（log-provider）

调用前**必须输出一行 log**：

```
[1.8d] 调用 log-provider：start=<bug_start> end=<bug_end> interfaces=<候选列表或[]>
```

执行（通过 dispatch.py，自动读取 `logProvider` 配置路由到对应 provider）：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_providers/dispatch.py" \
  query_errors_silent \
  --start <bug_start> \
  --end   <bug_end> \
  [--interfaces <path1,path2>]
```

记录返回结果到 `log_summary`，并**必须输出一行 log**：

| status | log_summary 值 | log 输出 |
|--------|---------------|---------|
| `ok` | `summary` 字段原文 | `[1.8d] log-provider 返回：有日志摘要，已写入 log_summary` |
| `not_configured` | `null`（静默跳过，不展示） | `[1.8d] log-provider 返回：not_configured，静默跳过` |
| `error` | `null`（静默跳过，不展示） | `[1.8d] log-provider 返回：错误 <message>，静默跳过` |
| `no_data` | `null`（静默跳过，不展示） | `[1.8d] log-provider 返回：无日志数据，静默跳过` |

> `log_summary` 赋值后在 Plan/报告中只展示真实摘要，not_configured/error/no_data 时静默跳过。
> 若需切换 provider：在 `~/.claude/pipelit/config.json` 设置 `"logProvider": "noop"` 即可禁用日志查询。

> **数据类 bug（数据不准/数量不对/显示有误）**：`log_summary` 必须包含实际 request payload 和 response payload，用于判断是后端逻辑问题还是数据源（StarRocks/DB）问题。

> log_summary 结果：L2 任务嵌入 Phase 2 Plan，L3 任务嵌入 Phase 1.3 分析报告。

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

（若 log_summary 不为 null，在此处追加观测云日志摘要）
<log_summary 内容>

确认后自动执行 →
━━━━━━━━━━━━━━━
```

**BOT_AUTO_EXECUTE 模式**：输出 Plan 后**不等待**，直接进入 Phase 3。

否则：等用户确认或修正后再进入 Phase 3。

**⚠ Plan 修正规则（重要）**：若用户对 Plan 提出任何修改（包括增删改动点、调整范围、指出遗漏），必须：
1. 输出修订版 Plan
2. **再次等待**用户明确回复"确认"/"ok"/"没问题"
3. **不得将"用户提出修改"本身视为确认**，修改后必须重走等待流程

---

## Phase 3：执行

### 3.1 创建分支（每个仓库独立执行）

任务可能涉及前端和后端两个仓库。**对每个涉及的仓库独立执行以下逻辑，不可跳过任一仓库**：

**执行规则（三段式）**：

1. `cd` 到该仓库路径，获取当前分支名
2. 判断：
   - 当前分支为 `master`/`main`/`dev` → 创建 `feat/feishu-{task_id 前 8 位}`
   - 当前分支为 `feat/feishu-{本任务 id 前 8 位}` → 直接使用，输出 `[3.1-<repo>] 复用已有分支: <branch>`
   - 当前分支为其他任意分支（`develop`、`release/xxx`、`feat/other-task` 等，不是主干也不是本任务分支）→ 通过 AskUserQuestion 询问用户：
     ```
     当前在分支 <branch>，不是主干分支。
     如何处理？
       ● 在当前分支继续开发（适合同一功能的延续）
       ○ 新建独立分支 feat/feishu-{task_id 前 8 位}
     ```
     用户选"继续"→ 使用当前分支；选"新建"→ 创建新分支
3. **强制输出 log**，每个仓库一行：

```
[3.1-frontend] 当前分支: master → 创建 feat/feishu-XXXXXXXX
[3.1-backend]  当前分支: master → 创建 feat/feishu-XXXXXXXX
```

4. 任一仓库跳过分支创建，必须输出原因：

```
[3.1-<repo>] 跳过原因: <reason>
```

**范围联动（与 Phase 2 Plan「范围」字段挂钩）**：

- 若 Plan 范围为「**仅前端**」→ 对后端仓库**跳过**分支创建，输出 `[3.1-backend] 跳过原因: 范围=仅前端`
- 若 Plan 范围为「**仅后端**」→ 对前端仓库**跳过**分支创建，输出 `[3.1-frontend] 跳过原因: 范围=仅后端`
- 若 Plan 范围为「**前后端**」→ 两个仓库都必须创建/确认分支，不可省略

**反例（禁止）**：

```
[3.1-frontend] 创建 feat/feishu-xxx
（后端没日志，直接在 master 上改）  ← 不允许！
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

### 3.5 用户验证（第 2 个人工介入点）

自检通过后，**暂停并让用户验证功能**：

```
━━━ 请验证功能 ━━━
改动文件:
  • <文件1> (+N -M)
  • <文件2> (+N -M)

验证建议:
  1. <根据改动内容给出的具体验证步骤>
  2. <如：刷新页面，检查搜索功能是否生效>

验证通过回复 "ok"，我将自动 commit + push + 标记完成。
如有问题请描述，我来修复。
━━━━━━━━━━━━━━━━━
```

**BOT_AUTO_EXECUTE 模式**：自检通过后**直接进入 3.6**，不暂停等待验证。

否则：
- 用户回复 "ok" / "通过" / "没问题" → 进入 3.6 自动完成所有后续步骤
- 用户描述了问题 → 修复后重新回到 3.3 验证

### 3.6 Commit

开始前记录 `git status` 快照，只 add 新增/修改的文件，绝不使用 `git add -A` 或 `git add .`。

```
<type>: <根据实际 diff 写的描述>

Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=<task_id>
Co-Authored-By: Claude <noreply@anthropic.com>
```

Type 判断：含"新增/添加" → `feat`，含"修复/bug" → `fix`，含"删除/重构" → `refactor`，含"优化" → `perf`，兜底 → `feat`。

### 3.7 Push + 标记完成（自动执行）

用户验证通过后，以下步骤全部自动执行，不再逐个确认：

```bash
# 推送（绝不推送到 master/main/dev）
git push origin <branch>

# 标记飞书任务完成
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" complete_task <task_id>
```

若 push 失败，报错并输出手动推送命令，不阻塞后续报告。

---

## Phase 4：收尾

### 4.1 输出报告

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
