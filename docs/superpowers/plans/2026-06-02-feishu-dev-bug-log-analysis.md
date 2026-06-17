# feishu-dev Bug 日志辅助分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 feishu-dev 处理 bug 类任务时，自动查询观测云日志并将摘要嵌入 Plan（L2）或分析报告（L3）。

**Architecture:** feishu-dev Phase 1.7 之后插入 Phase 1.8（bug 判断→接口预定位→时间推断→调用 guance），guance-log-analysis 新增静默模式入口供程序化调用，两个 skill 通过 `GUANCE_SILENT_MODE` 约定协作。

**Tech Stack:** Markdown skill files（无代码改动，仅 prompt 工程）

---

## 文件改动总览

| 文件 | 操作 | 内容 |
|------|------|------|
| `skills/guance-log-analysis/SKILL.md` | 修改 | 头部插入静默模式说明 |
| `skills/feishu-dev/SKILL.md` | 修改 | Phase 1.7 后插入 Phase 1.8；L2 Plan 输出加 log 摘要节；L3 报告加 log 佐证节 |

---

## Task 1：给 guance-log-analysis 加静默模式

**Files:**
- Modify: `skills/guance-log-analysis/SKILL.md`

- [ ] **Step 1：在 `# 观测云日志分析` 标题之后、`脚本：` 行之前，插入静默模式说明块**

在文件第 9 行（`脚本：...` 那行）之前插入以下内容：

```markdown
## 静默模式（GUANCE_SILENT_MODE）

当 prompt 包含 `GUANCE_SILENT_MODE` 时，进入静默模式，由其他 skill 程序化调用：

**跳过**：Phase 0 配置引导交互、Phase 1 时间段询问
**直接使用** prompt 中传入的参数：
- `start`：查询开始时间（格式同 Phase 1）
- `end`：查询结束时间
- `interfaces`：候选接口路径列表（可为空）

**执行策略（懒加载兜底）**：

```
Step A：若 interfaces 不为空 → 带接口关键词过滤的精准查询
        有结果 → 直接输出精简摘要，结束
        无结果 → 执行 Step B

Step B：全量查询（不带过滤），从结果中找与 bug 描述最相关的报错
```

**配置未就绪**：直接输出 `GUANCE_NOT_CONFIGURED`，不展示引导。

**输出格式**（精简摘要，供调用方嵌入）：

```
━━ 🔍 观测云 Log 摘要 ━━━━━━━━━━━━━━━━━
时间段: <start> ~ <end>
错误总数: <N> 条
关联接口: <接口路径，若有>

高频报错:
  • <接口路径> → <错误信息>  ×N 次
  • <接口路径> → <错误信息>  ×N 次

可能关联: <结合 bug 描述推断的关联点>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

无数据时输出：
```
该时段未发现相关错误日志（共查询 <N> 条记录）
```

---

```

- [ ] **Step 2：确认插入位置正确**

读取 `skills/guance-log-analysis/SKILL.md`，确认：
- 静默模式块在 `脚本：` 行之前
- `## Phase 0` 仍然完整存在
- 文件整体结构未损坏

- [ ] **Step 3：Commit**

```bash
git add skills/guance-log-analysis/SKILL.md
git commit -m "feat(guance): 新增 GUANCE_SILENT_MODE 静默调用入口"
```

---

## Task 2：feishu-dev 加 Phase 1.8（bug 判断 + 接口预定位 + 时间推断 + 调用 guance）

**Files:**
- Modify: `skills/feishu-dev/SKILL.md`

- [ ] **Step 1：在 Phase 1.7 结尾（`---` 分隔线）之后、`## Phase 2` 之前，插入 Phase 1.8**

在 `### 1.7 定位目标文件` 结束后的 `---` 之后插入以下内容：

```markdown
### 1.8 Bug 日志辅助（仅 bug 任务触发）

#### 1.8a 判断是否为 bug 任务

读完任务（含图片、附件）后，**语义判断**任务意图是否为"某个功能出了问题需要排查"。

包括但不限于：功能异常、用户投诉、页面报错、数据不对、接口失败、体验问题、性能异常等。不依赖关键词匹配，以任务整体意图为准。

**判断为 bug 任务** → 继续 1.8b。**否则跳过整个 1.8**。

#### 1.8b 代码接口预定位

结合 1.7 已定位的目标文件及任务描述，在前端项目目录 grep API 调用，找候选接口路径：

```bash
# 搜索 api 目录下与功能模块相关的接口定义
grep -rn "url\|path\|api" <frontend_path>/src/api --include="*.ts" | grep -i "<功能关键词>"
```

读取命中文件，提取与当前 bug 功能模块语义匹配的接口路径，得到候选列表（可为空）。

#### 1.8c 时间推断

综合以下信息语义推断 bug 发生时间点（优先级从高到低）：

1. 任务描述里的时间线索（"今天下午两点"、"刚才"、"昨晚"、"上午十点左右"等）
2. 截图里可见的时间信息（系统时间栏、日志时间戳、界面上的时间）
3. fallback：`task.created_at`（任务创建时间）

时间窗口由 Claude 根据线索灵活判断：
- "刚才" / "刚刚" → 往前 30 分钟
- "今天上午" / "今天下午" → 往前 4 小时
- 具体时间点 → 往前 1 小时
- 无任何线索（fallback） → 往前 1 小时

记录：
- `bug_start`：推断时间点 - 窗口
- `bug_end`：推断时间点 + 15 分钟

#### 1.8d 调用观测云查询

invoke guance-log-analysis，prompt 包含：

```
GUANCE_SILENT_MODE
start: <bug_start>
end: <bug_end>
interfaces: [<候选接口路径列表，可为空>]
```

记录返回结果到 `log_summary`：

| guance 返回 | log_summary 值 |
|-------------|---------------|
| 精简摘要内容 | 摘要原文 |
| `GUANCE_NOT_CONFIGURED` | `"⚠️ 观测云未配置，跳过日志分析"` |
| 无数据 / 报错 | `null`（静默跳过，不展示） |

```

- [ ] **Step 2：修改 Phase 2 Plan 输出，插入 log_summary 节**

在 Phase 2 的 Plan 模板里，`确认后自动执行 →` 行**之前**插入：

```markdown
{{#if log_summary}}
{{log_summary}}
{{/if}}
```

实际写入文件时，用注释说明形式（不是模板语法），改为：

```
（若 log_summary 不为 null，在此处追加以下内容）

<log_summary 内容>

```

具体：在 Plan 模板的 `确认后自动执行 →` 行之前，加入：

```
**若查询到相关 log，追加：**
<log_summary 摘要>
```

- [ ] **Step 3：修改 Phase 1.3 L3 报告输出，插入 log 佐证节**

在 L3 报告模板的 `涉及范围:` 之后、`建议拆分:` 之前插入：

```markdown
（若 log_summary 不为 null，在涉及范围之后插入）

━━ 🔍 观测云 Log 佐证 ━━
<log_summary 内容>
结合日志结论: <log 数据对上述定位的印证或修正>
━━━━━━━━━━━━━━━━━━━━━━
```

具体在 L3 报告模板 `涉及范围:` 块后面追加该节。

- [ ] **Step 4：确认整体结构**

读取 `skills/feishu-dev/SKILL.md`，确认：
- Phase 顺序：1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → **1.8** → Phase 2
- 1.8 的四个子节均存在（1.8a / 1.8b / 1.8c / 1.8d）
- L3 报告模板包含 log 佐证节
- L2 Plan 模板包含 log 摘要节
- 原有内容无损坏

- [ ] **Step 5：Commit**

```bash
git add skills/feishu-dev/SKILL.md
git commit -m "feat(feishu-dev): Phase 1.8 bug 日志辅助分析，自动查观测云 log 嵌入 Plan/报告"
```

---

## 自检 checklist

完成两个 task 后，整体验证：

- [ ] `guance-log-analysis/SKILL.md`：静默模式块在 `脚本：` 之前，Phase 0~3 完整保留
- [ ] `feishu-dev/SKILL.md`：Phase 1.8 在 1.7 之后、Phase 2 之前
- [ ] L2 Plan 输出模板有 log_summary 节
- [ ] L3 报告模板有 log 佐证节
- [ ] 无 TBD / TODO / 占位符
