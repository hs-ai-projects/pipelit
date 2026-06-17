# Lesson Sniffer 试验 — Design

- **日期**：2026-06-03
- **作者**：otsan + Claude
- **状态**：Design（待 review）
- **定位**：**一周 scratch 试验**，非 pipelit 正式能力

---

## 1. 目的

测试一个想法：**用 Claude Code SessionEnd hook + 廉价模型，是否能从对话里自动抽出"用户纠正过 AI"的边界 case，沉淀成可读条目**。

试验通过 → 决定是否做成正式机制。
试验失败 → 删目录，pipelit 主体不受影响。

## 2. 范围

**包括（in scope）**：
- 只挂在 `feishu-dev` 会话上（sniff.py 内部判断）
- 单文件 jsonl 沉淀，不做召回
- 一周试验期

**不包括（out of scope）**：
- ❌ 召回端（试验期先不做，攒数据为主）
- ❌ 其他 skill（不接 release / changelog / guance）
- ❌ 跨用户、跨机器同步
- ❌ 进 pipelit marketplace、改 SKILL.md、改 package.json
- ❌ 错误重试、可观测、监控
- ❌ 任何 config.json 字段

## 3. 文件清单

```
pipelit/
├── skills/feishu-dev/SKILL.md       ← 0 改动
├── package.json                      ← 0 改动
├── scripts/feishu_api.py             ← 0 改动
├── scripts/experiments/              ← 试验目录（整目录 .gitignore）
│   └── lesson_sniffer/
│       ├── sniff.py                  ← SessionEnd 触发的分析器
│       ├── install_hook.sh           ← 装 hook（往 ~/.claude/settings.json 追加配置）
│       ├── uninstall_hook.sh         ← 拔 hook
│       ├── lessons.jsonl             ← 沉淀产物
│       └── README.md                 ← 试验说明 + 评价标准 + 卸载步骤
└── .gitignore                        ← 加一行 scripts/experiments/
```

## 4. 触发链路

```
Claude Code 会话结束
  ↓ SessionEnd hook（在 ~/.claude/settings.json）
sniff.py
  ↓ 步骤 A：定位 session log
  ↓        从 hook 透传的环境变量取（具体变量名在 plan 期间查
  ↓        Claude Code 文档确认；候选：CLAUDE_SESSION_LOG / 类似）
  ↓        判断本次会话是否涉及 feishu-dev：
  ↓        扫 log 找 "feishu-dev" / "/feishu-dev" 字符串
  ↓        不涉及 → exit 0
  ↓ 步骤 B：从 session log 抽出 user 和 assistant 的纯文本消息
  ↓        丢弃：tool_use 调用、tool_result 返回、system reminder
  ↓        保留：用户输入文本、AI 回答文本
  ↓        拼成 prompt
  ↓ 步骤 C：调用 haiku（claude-haiku-4-5-20251001）
  ↓        Prompt 模板：见 §6
  ↓ 步骤 D：解析返回
  ↓        - 若 LLM 返回有效 lesson JSON → 追加一行到 lessons.jsonl
  ↓        - 若 LLM 返回 null → 也追加一行 {lesson: null, reason: "..."}
  ↓        - 任何异常 → exit 0 静默
```

**关键设计点**：
- **全静默**：所有失败 `exit 0`，绝不打扰主流程
- **null 也记一行**：让用户区分"sniff 没跑" vs "sniff 跑了但没抽到"
- **只针对 feishu-dev**：sniff.py 内部判断，hook 全局触发但绝大多数会话会被早期 return

## 5. 数据 Schema（lessons.jsonl）

每行一个 JSON：

```jsonl
{"ts":"2026-06-04T10:23+08:00","session_id":"...","lesson":"服务器 Python 必须用 ~/pipelit/.venv/bin/python","why":"上次 python3 找不到 lark_oapi","tags":["python-env","server"]}
{"ts":"2026-06-04T15:11+08:00","session_id":"...","lesson":"feishu_api.get_task_full 要用 user_access_token","why":"app token 拿不到个人任务","tags":["feishu-api","auth"]}
{"ts":"2026-06-05T09:02+08:00","session_id":"...","lesson":null,"reason":"本次会话没有发现纠正信号"}
```

**字段说明**：
- `ts`：ISO 8601 本地时区
- `session_id`：Claude Code 会话 ID（来自 hook 环境变量）
- `lesson`：抽出的边界（null = 没抽到）
- `why`：上下文 / 原因（帮助以后回看时理解）
- `tags`：自由 tag，由 LLM 自己生成（不预定义 enum）
- `reason`：仅 lesson=null 时存在，说明为什么没抽到

## 6. LLM Prompt 模板（草案，可在实现期调整）

```
你是会话审计员。下面是一段我和 AI 助手的对话日志。

任务：判断对话中是否出现「用户纠正/反驳/补充了 AI 的某个行为或假设」。

规则：
- 「纠正」=用户明确指出 AI 做错、做漏、做反、用错工具/路径/方式
- 一般性补充信息（"项目用的是 Vue 3"）不算纠正
- 用户的"嗯"、"好"、"你说得对"不算纠正
- 一次会话最多抽 1 条最重要的纠正

输出（严格 JSON）：
- 有纠正 → {"lesson": "...", "why": "...", "tags": ["...", "..."]}
- 没纠正 → {"lesson": null, "reason": "..."}

对话日志：
<<<
{conversation}
>>>
```

## 7. 隔离设计（防止"渗入通用版"）

| 隔离层 | 实现 |
|---|---|
| **代码** | 全部在 `scripts/experiments/lesson_sniffer/`，目录名带 `experiments` 显式标记 |
| **plugin manifest** | 0 改动 `package.json` / `marketplace.json` |
| **SKILL.md** | 0 改动任何 skill 文件 —— feishu-dev 完全不知情 |
| **git** | `.gitignore` 整个 `scripts/experiments/`，别人 clone 拿不到 |
| **Claude Code 配置** | hook 写在 `~/.claude/settings.json`，不在 pipelit 仓库里 |
| **卸载** | `bash uninstall_hook.sh && rm -rf scripts/experiments/lesson_sniffer/` —— 回到从未装过的状态 |

## 8. 一周后的评价标准

试验结束日：2026-06-10。

**评价方式**：
1. 打开 `lessons.jsonl`
2. 手工对所有非 null 条目逐条评分（标记 `useful` / `noise` / `wrong`）
3. 同时检查："那一周里我确实纠正过的事，sniff 漏了几件"

**通过门槛**：
- 非 null lesson 至少 ≥ 5 条
- `useful` 比例 ≥ 50%
- 漏抽率 ≤ 30%（凭印象）

**通过 → 下一步选项**：
- (a) 把 sniff 正经写进 plugin，加召回端
- (b) 改进 prompt 后继续试验另一周
- (c) 改 SessionEnd hook → commit-msg hook（看哪种信号更准）

**不通过 → 删目录、删 hook、结束**。

## 9. 错误处理

| 失败点 | 处理 |
|---|---|
| hook 没触发 | 不可观测，需要在 README 里写"如何手工验证" |
| sniff.py 启动失败（Python 错误） | exit 0，stderr 重定向到 `lesson_sniffer/sniff.err.log` |
| 找不到 session log | exit 0 静默 |
| `ANTHROPIC_API_KEY` 缺失 | exit 0 静默 |
| haiku API 调用失败 / 超时（30s） | exit 0 静默 |
| haiku 返回不是合法 JSON | exit 0 静默，但记一行 `{lesson: null, reason: "llm output malformed"}` |
| jsonl 写入失败 | exit 0 静默 |

## 10. 不在本 design 内的后续问题（写下来防止以后忘）

- 怎么做"召回端"（试验通过才考虑）
- 怎么扩展到其他 skill（试验通过才考虑）
- 怎么处理 lessons 老化、去重、改写（先攒、不管）
- 怎么处理多用户（YAGNI）
