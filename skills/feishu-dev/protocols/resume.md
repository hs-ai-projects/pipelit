# feishu-dev 续接协议

> 解决 context 压缩/清空后任务中断的问题（反馈 #19）。
> 每个 Phase 开始/结束写 `<workdir>/.feishu-dev-state.json`。
> 新 session 启动时自动检测并询问是否续接。

---

## 状态文件 schema

写到当前工作目录（`feishu-dev` 任务所在 repo）的 `.feishu-dev-state.json`：

```json
{
  "schema_version": "1.0",
  "task_id": "feishu-XXXXXXXXXXXXXXXX",
  "task_summary": "优化广告列表翻页",
  "skill": "feishu-dev",
  "level": "L2",
  "current_phase": "3",
  "branch": "feat/feishu-XXXXXXXXXXXXXXXX",
  "repos": [
    {"label": "frontend", "path": ".", "branch": "feat/feishu-XXXXXXXXXXXXXXXX"},
    {"label": "backend", "path": "../ads", "branch": "feat/feishu-XXXXXXXXXXXXXXXX"}
  ],
  "pending_actions": ["commit", "push", "mark_done"],
  "plan_summary": "修改 AdList.vue 第 45 行翻页逻辑，更新 useAds composable",
  "started_at": "2026-06-05T10:00:00+08:00",
  "last_updated": "2026-06-05T10:30:00+08:00",
  "bot_auto_execute": false
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 飞书任务 ID |
| `task_summary` | string | 任务标题（≤100字） |
| `level` | "L2" \| "L3" | 分级结果 |
| `current_phase` | string | 当前所在 Phase（"1" / "2" / "3" / "3.5" / "4"） |
| `branch` | string | 创建的分支名 |
| `repos` | array | 涉及的所有仓库 |
| `pending_actions` | array | 还未完成的动作 |
| `plan_summary` | string | Phase 2 确认的 Plan 摘要（≤200字） |
| `bot_auto_execute` | bool | 是否 BOT_AUTO_EXECUTE 模式 |

---

## 写状态文件的时机

| 时机 | `current_phase` | `pending_actions` |
|---|---|---|
| Phase 1 开始（拉取任务后） | `"1"` | `["plan", "implement", "commit", "push"]` |
| Phase 2 完成（Plan 已确认） | `"2-done"` | `["implement", "commit", "push"]` |
| Phase 3 开始 | `"3"` | `["implement", "commit", "push"]` |
| Phase 3.5 等待用户验证 | `"3.5"` | `["commit", "push", "mark_done"]` |
| Phase 4 完成 | 删除文件 | — |

---

## 启动时检测

**在 MODE-CHECK 之前，第一步执行**：

```bash
# 检查状态文件
ls .feishu-dev-state.json 2>/dev/null && echo "found" || echo "not found"
```

若文件存在：
1. 读取 `last_updated` 字段
2. 若距今 < 24h → 输出一行 log：`[RESUME-CHECK] 发现未完成任务: <task_summary>，Phase: <current_phase>，<N>h 前`
3. 通过 AskUserQuestion 询问：

```
⏸ 发现上次未完成的任务：<task_summary>
最后更新：<last_updated>（<N>h 前）
当前进度：Phase <current_phase>，待完成：<pending_actions>

如何继续？
  ● 续接（从 Phase <current_phase> 恢复）
  ○ 放弃，重新开始新任务
  ○ 仅查看状态，不执行
```

若文件不存在，或距今 ≥ 24h，跳过此步骤。

---

## 续接流程

按 `current_phase` 跳转：

| `current_phase` | 恢复动作 |
|---|---|
| `"1"` | 重新读取任务（`get_task_full`），从 Phase 1.6 开始 |
| `"2-done"` | 展示已保存的 `plan_summary` → 直接进入 Phase 3 |
| `"3"` | 检查分支是否存在 + 未 commit 的修改 → 继续 Phase 3 |
| `"3.5"` | 询问"代码已验证了吗" → 若是，直接 Phase 4；否则重新展示验证清单 |

---

## 关键不变量

- **写状态文件不能阻断主流程**：写失败只输出 warn，不退出
- **Phase 4 完成必须删除状态文件**：`rm .feishu-dev-state.json`（若存在）
- **L3 任务不写状态文件**：L3 只输出报告，没有"续接"需求
- **状态文件写到任务的主 repo 根目录**，不写到工具目录

---

## 状态文件写法示意

Phase 1 开始时写：

```bash
node -e "const fs=require('fs');fs.writeFileSync('.feishu-dev-state.json',JSON.stringify({schema_version:'1.0',task_id:'<task_id>',task_summary:'<summary>',skill:'feishu-dev',level:'<L2/L3>',current_phase:'1',branch:'',repos:[],pending_actions:['plan','implement','commit','push'],plan_summary:'',started_at:'<ISO8601+08:00>',last_updated:'<ISO8601+08:00>',bot_auto_execute:false},null,2))"
```

Phase 4 完成时清理：

```bash
rm -f .feishu-dev-state.json
```
