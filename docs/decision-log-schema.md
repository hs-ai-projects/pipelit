# Decision Log Schema

> Pipelit 所有 skill 的决策日志统一格式。
> 目的：跑两次同任务能 diff、换 AI 模型能验证一致、出问题能追溯。
>
> Stage 0 产物 —— Stage 1/2 各 Task 都会落盘 audit JSON 到这里规定的位置。

---

## 核心问题

之前的 SKILL.md 是散文式："读完任务自我评估，满足条件继续"——

- ❌ 没记录"评估了什么 → 得到什么结论"
- ❌ 换一个 AI 模型，可能得出不同判定，无法对比
- ❌ 同一个任务跑两次结果不一样，不知道哪里飘了

**解决**：每个关键决策点都落一份 audit JSON，可 diff、可追溯、可作为后续 Task 的回归基线。

---

## 落地位置

```
~/.claude/pipelit/decision-logs/
  └── 2026-06-05/                      # 按日期分目录
      ├── <task_id>-feishu-dev.json    # feishu-dev 单次跑的完整决策链
      ├── <task_id>-release.json       # release 单次跑的完整决策链
      └── <task_id>-guance.json        # guance 单次查询的参数和返回摘要
```

**约定**：

- 文件名 = `<task_id>-<skill>.json`（task_id 用前 8 位 + 时间戳防重）
- 一次完整 skill 跑 = 一份文件（即使中途用户暂停或取消）
- 跑两次相同任务 = 两份文件，可用 `diff` 工具对比

---

## 顶层 Schema

```json
{
  "schema_version": "1.0",
  "skill": "feishu-dev | release | guance | ...",
  "task_id": "前8位或mock-id",
  "task_summary": "广告报告创建失败",
  "started_at": "2026-06-05T10:00:00+08:00",
  "completed_at": "2026-06-05T10:15:00+08:00",
  "status": "completed | partial | cancelled | failed",
  "bot_auto_execute": false,
  "model_hint": "claude-opus-4-7-1m",

  "phases": [
    { "phase": "1.3", "decision": {...} },
    { "phase": "1.7", "decision": {...} },
    { "phase": "1.8d", "decision": {...} },
    { "phase": "2", "decision": {...} },
    { "phase": "3.1", "decision": {...} }
  ],

  "final_decision": {
    "level": "L2",
    "matched_rule": "default-l2"
  }
}
```

---

## 各 skill 关键 phase 的 decision 字段

### feishu-dev Phase 1.3 复杂度判定

```json
{
  "phase": "1.3",
  "decision_type": "level_classification",
  "level": "L2",
  "matched_rule": "rule-N-name",
  "rule_priority": 6,
  "evidence": {
    "candidate_files": 2,
    "desc_length": 132,
    "has_screenshot": true,
    "has_attachment": false,
    "is_bug_task": false,
    "matched_keywords": [],
    "feishu_tags": []
  },
  "fallback_attempted": false
}
```

**规则名约定**：`rule-<priority>-<short-name>`，例如 `rule-1-keyword-incident`、`rule-5-vague-description`、`default-l2`。
完整规则表见 Stage 2 Task 2.1 产物 `skills/feishu-dev/rules/classification.md`。

---

### feishu-dev Phase 1.7 接口/文件定位

```json
{
  "phase": "1.7",
  "decision_type": "file_targeting",
  "candidate_files": [
    {"path": "src/views/AdList.vue", "match_source": "grep"},
    {"path": "src/components/AdTable.vue", "match_source": "screenshot_url"}
  ],
  "chosen_files": ["src/views/AdList.vue"],
  "user_disambiguation_required": false,
  "convergence_method": "single_candidate"
}
```

`match_source` 取值：`grep` / `screenshot_url`（截图 URL 优先）/ `user_input` / `task_description`。

---

### feishu-dev Phase 1.8 bug 日志辅证

```json
{
  "phase": "1.8",
  "decision_type": "bug_log_assist",
  "is_bug_task": true,
  "bug_judgment_reason": "用户描述「失败」+「服务器错误」",

  "interface_candidates": ["/api/ads/create-ads/report"],
  "time_window": {
    "start": "2026-06-04T13:30:00+08:00",
    "end": "2026-06-04T14:45:00+08:00",
    "inference_source": "description_time_hint",
    "raw_hint": "今天下午两点半",
    "window_size_minutes": 75
  },

  "guance_call": {
    "step": "A",
    "step_a_hit": true,
    "step_b_fallback": false
  },
  "guance_result": "summary_returned | GUANCE_NOT_CONFIGURED | GUANCE_ERROR | GUANCE_NO_DATA | GUANCE_TIME_INVALID",
  "log_summary_embedded": true
}
```

`inference_source` 取值：`description_time_hint` / `screenshot_timestamp` / `task_created_at_fallback`。

---

### feishu-dev Phase 3.1 分支策略

```json
{
  "phase": "3.1",
  "decision_type": "branch_strategy",
  "repos": [
    {
      "repo": "frontend",
      "path": "/path/to/frontend",
      "current_branch": "master",
      "action": "create",
      "new_branch": "feat/feishu-12345678",
      "skip_reason": null
    },
    {
      "repo": "backend",
      "path": "/path/to/backend",
      "current_branch": "master",
      "action": "create",
      "new_branch": "feat/feishu-12345678",
      "skip_reason": null
    }
  ]
}
```

`action` 取值：`create` / `switch_existing` / `skip`。`skip_reason` 必须在 action=skip 时填写。

---

### release Phase 1.3 版本号判定

```json
{
  "phase": "1.3",
  "decision_type": "version_bump",
  "tag_prefix": "v",
  "last_tag": "v1.2.5",
  "suggested_tag": "v1.3.0",
  "bump_type": "minor",
  "matched_rule": "rule-4-feat",
  "evidence": {
    "commits_total": 20,
    "feat_count": 2,
    "fix_count": 5,
    "breaking_count": 0,
    "deleted_public_exports": [],
    "deleted_api_paths": []
  },
  "warnings": []
}
```

警告字段示例（Stage 2 Task 2.3 之后）：

```json
"warnings": [
  {
    "type": "deleted_export_without_breaking_marker",
    "items": ["src/utils/date.ts:formatDate"],
    "severity": "high"
  }
]
```

---

### release Phase 3.x 状态机（Stage 2 Task 2.2 之后）

```json
{
  "phase": "3.x",
  "decision_type": "state_transition",
  "from_state": "COMMITTED",
  "to_state": "PUSHING",
  "trigger": "auto",
  "timestamp": "2026-06-05T10:10:00+08:00"
}
```

`from_state` / `to_state` 取值见 `skills/release/state-machine.md`：
`IDLE` / `PREVIEWED` / `COMMITTED` / `PUSHING` / `PUSHED` / `PARTIAL_PUSHED` / `COMPLETED` / `CANCELLED` / `ROLLBACK_READY`。

---

### release Phase 3.5b 卡片预览（Task 1.6）

```json
{
  "phase": "3.5b",
  "decision_type": "card_preview_confirm",
  "sections_count": 3,
  "entries_with_task_link": 5,
  "entries_with_mention": 5,
  "entries_no_link": 1,
  "image_source": "openai_generated_with_mascot_ref",
  "user_choice": "send | edit | cancel",
  "edit_applied": false
}
```

`image_source` 取值：`user_uploaded_local` / `openai_generated_with_mascot_ref` / `fallback_previous_release` / `no_image`。

---

### guance 静默查询

```json
{
  "schema_version": "1.0",
  "skill": "guance",
  "called_from": "feishu-dev",
  "input": {
    "start": "2026-06-04T13:30:00+08:00",
    "end": "2026-06-04T14:45:00+08:00",
    "interfaces": ["/api/ads/create-ads/report"]
  },
  "validation": {
    "time_format_valid": true,
    "timezone_present": true
  },
  "step_a_result": {
    "hit": true,
    "result_count": 12
  },
  "step_b_fallback": false,
  "return_token": "summary_returned"
}
```

`return_token` 取值：`summary_returned` / `GUANCE_NOT_CONFIGURED` / `GUANCE_ERROR:<reason>` / `GUANCE_NO_DATA` / `GUANCE_TIME_INVALID:<reason>`。

---

## 写入约定（落地实施细则）

### 何时写

- **每个 Phase 结束**追加一个 `phases[]` 元素，不要全部跑完再一次性写
- **用户暂停或取消**也要写完当前 phase 再退出，并标 `status: "cancelled"`
- **失败**写 `status: "failed"` 并在 `failure` 字段记录错误

### 怎么写

- 用 `scripts/decision_log.py`（Stage 2 落地，目前可手动 echo）封装：
  - `decision_log.py start <skill> <task_id>` → 创建文件骨架
  - `decision_log.py phase <task_id> <phase> @decision.json` → 追加 phase
  - `decision_log.py finish <task_id> <status>` → 写 completed_at + status
- 文件锁：同一 task_id 文件用 advisory lock 防并发

### 隐私

- **不写凭据**（app_secret、API key 等）
- **task_summary 截断到 100 字**
- **不写完整 commit body**（只保留 hash + Feishu-Task URL）

---

## 使用决策日志

### 跑两次对比

```bash
diff \
  ~/.claude/pipelit/decision-logs/2026-06-05/abc12345-feishu-dev.json \
  ~/.claude/pipelit/decision-logs/2026-06-05/abc12345-feishu-dev-2.json
```

期望差异：仅 `started_at` / `completed_at` / `phases[].timestamp`。

如果 `final_decision.level` 不同 → 决策不稳定 → 回 Task 2.1 加强规则。

### 换模型对比

跑前在环境变量记录模型：

```bash
PIPELIT_MODEL=claude-sonnet-4-6 /feishu-dev <task_id>
PIPELIT_MODEL=claude-opus-4-7-1m /feishu-dev <task_id>
```

audit 顶层的 `model_hint` 会记录。diff 两份输出 → 决策不一致 = 规则太依赖 AI 主观判断。

### 复盘 "为什么这次判错"

```bash
python3 scripts/audit.py why <task_id>
```

输出每个 phase 的 `matched_rule` 和 `evidence`，定位到具体哪条规则不合理。

（scripts/audit.py 是 Stage 5 Task 5.3 产物，目前手动看 JSON）

---

## 校验 Schema

简易校验：

```bash
python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
required = ['schema_version','skill','task_id','started_at','status','phases']
for k in required:
    assert k in data, f'missing {k}'
print('ok')
" <log_file>
```

完整 JSON Schema（机器校验）见 Stage 4 Task 4.3 产物 `output-contracts/decision-log.schema.json`。
